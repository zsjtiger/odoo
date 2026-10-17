"""The base class of the string fields: their setup, their conversions and their description. The translations, the writes and the queries are split by concern in the other modules."""

from __future__ import annotations

import typing
from hashlib import sha256
from operator import attrgetter
from markupsafe import escape as markup_escape
from psycopg2.extras import Json as PsycopgJson
from odoo.exceptions import ValidationError
from odoo.tools import SQL, sql
from odoo.tools.misc import SENTINEL, Sentinel
from odoo.tools.text.translate import StoredTranslations, ParsedTranslation
from odoo.orm.fields import Field, _logger

if typing.TYPE_CHECKING:
    from collections.abc import Callable
    from odoo.orm.database.query import TableSQL


class BaseString(Field[str | typing.Literal[False]]):
    """ Abstract class for string fields. """
    translate: bool | Callable[[Callable[[str], str | None], str], str] = False  # whether the field is translated
    is_text = True
    falsy_value = ''
    def __init__(self, string: str | Sentinel = SENTINEL, **kwargs):
        # translate is either True, False, or a callable
        if 'translate' in kwargs and not callable(kwargs['translate']):
            kwargs['translate'] = bool(kwargs['translate'])
        super().__init__(string=string, **kwargs)
    _related_translate = property(attrgetter('translate'))
    def _compute_related(self, records):
        if records.env.context.get('edit_translations'):
            records = records.with_context(edit_translations=None, check_translations=True)
        super()._compute_related(records)
    def _description_translate(self, env):
        return bool(self.translate)
    def setup_related(self, model):
        super().setup_related(model)
        if self.store and self.translate:
            _logger.warning("Translated stored related field (%s) will not be computed correctly in all languages", self)
    def get_depends(self, model):
        if self.translate and self.store:
            dep, dep_ctx = super().get_depends(model)
            if dep_ctx:
                _logger.warning("Translated stored fields (%s) cannot depend on context", self)
            return dep, ()
        return super().get_depends(model)
    def _convert_db_column(self, model, column):
        # specialized implementation for converting from/to translated fields
        if self.translate or column['udt_name'] == 'jsonb':
            sql.convert_column_translatable(model.env.cr, model._table, self.name, self.stored_sql_column_type)
        else:
            sql.convert_column(model.env.cr, model._table, self.name, self.stored_sql_column_type)
    def convert_to_column(self, value, record, values=None, validate=True):
        # domain condition `(name, '=', {'en_US': 'English, 'fr_FR': 'French'})` is not supported
        assert not (self.translate and isinstance(value, dict))
        return self.convert_to_cache(value, record, validate)
    def convert_to_column_insert(self, value, record, values=None, validate=True):
        if value is False or value is None or not self.translate:
            return super().convert_to_column_insert(value, record, values, validate)
        cache_value = self.convert_to_cache(value, record, validate)
        if cache_value is None:
            return None
        lang = record.env.lang or 'en_US'
        if isinstance(cache_value, str):
            return PsycopgJson({'en_US': cache_value, lang: cache_value})
        if isinstance(cache_value, StoredTranslations):
            return PsycopgJson(cache_value)
        # assert isinstance(cache_value, dict)
        cache_value.setdefault('en_US', cache_value.get(lang, next(iter(cache_value.values()))))
        StoredTranslations(cache_value).validate(record.env, self)
        return PsycopgJson(cache_value)
    def get_column_update(self, record):
        if not self.translate:
            return super().get_column_update(record)

        assert self not in record.env._field_depends_context, f"translated field {self} cannot depend on context"
        value = record.env.transaction.field_data[self][record.id]
        if value is None:
            return None
        if callable(self.translate):
            return PsycopgJson(value)
        # (is_partial, translations)
        if not isinstance(value, StoredTranslations):
            return PsycopgJson((True, value))
        if not dict.__contains__(value, 'en_US'):  # noqa: PLC2801
            # usually impossible, but best effort to fixup the corrupted data
            _logger.warning("auto fix StoredTranslations %s for record %s", dict(value), record)
            value['en_US'] = next(iter(value.values()))
        return PsycopgJson((False, value))
    def convert_to_cache(self, value, records, validate=True):
        """
        Cache format
        ------------
        - non-translate: ``None | str``
        - translate: ``None | str | dict[str, str] | StoredTranslations``
        """
        if value is None or value is False:
            return None

        if self.translate and isinstance(value, dict):
            if isinstance(value, StoredTranslations):
                return value

            active_langs = records.env['res.lang']._get_active_by('code')
            converted = {
                lang: cache_val
                for lang, lang_value in value.items()
                if (lang in active_langs or lang == 'en_US')
                and (cache_val := self.convert_to_cache(lang_value, records, validate)) is not None
            }
            if validate and len(converted) != len(value):
                if any(lang not in active_langs and lang != 'en_US' for lang in value):
                    raise ValidationError(records.env._("Some of the languages are not active: %s", value))
                raise ValidationError(records.env._("Some of the translations are False: %s", value))
            return converted

        value = value.decode() if isinstance(value, bytes) else str(value)
        if validate:
            return self._validated_cache_value(value, records.env)
        return value
    def _validated_cache_value(self, value: str, env) -> str:
        return _cache._validated_cache_value(self, value, env)
    def convert_to_record(self, value, record):
        if value is None:
            return False
        if not self.translate:
            return value
        if isinstance(value, dict):
            lang = self.translation_lang(record.env)
            # raise a KeyError for the __get__ function
            value = value[lang]
        if (
            callable(self.translate)
            and record.env.context.get('edit_translations')
            and (translated_terms := ParsedTranslation(self, value).terms)
        ):
            field_ = self
            record_ = record
            while not field_.store and field_.related:
                record_ = record_.mapped(field_.related.rsplit('.', 1)[0])[:1]
                field_ = field_.related_field
            if field_ is not self:
                return field_.convert_to_record(value, record_)

            base_lang = record._get_base_lang()
            lang = record.env.lang or 'en_US'
            delay_translation = value != record.with_context(edit_translations=None, check_translations=None, lang=lang)[self.name]

            if lang != base_lang:
                base_value = record.with_context(edit_translations=None, check_translations=True, lang=base_lang)[self.name]
                base_terms = ParsedTranslation(self, base_value).terms
                if len(base_terms) != len(translated_terms):
                    # term number mismatch, ignore all translations
                    value = base_value
                    translated_terms = base_terms
                get_base = dict(zip(translated_terms, base_terms)).__getitem__
            else:
                get_base = lambda term: term

            translations = dict(self._get_stored_translations(record))

            # use a wrapper to let the frontend js code identify each term and
            # its metadata in the 'edit_translations' context
            def translate_func(term):
                source_term = get_base(term)
                if lang == base_lang or (source_term != term and lang in translations):
                    translation_state = 'translated'
                else:
                    translation_state = 'to_translate'

                translation_source_sha = sha256(source_term.encode()).hexdigest()

                return (
                    '<span '
                        f'''{'class="o_delay_translation" ' if delay_translation else ''}'''
                        f'data-oe-model="{markup_escape(record._name)}" '
                        f'data-oe-id="{markup_escape(record.id)}" '
                        f'data-oe-field="{markup_escape(self.name)}" '
                        f'data-oe-translation-state="{translation_state}" '
                        f'data-oe-translation-source-sha="{translation_source_sha}"'
                    '>'
                        f'{term}'
                    '</span>'
                )
            # pylint: disable=not-callable
            value = self.translate(translate_func, value)
        return value
    def convert_to_write(self, value, record):
        return value
    def _get_stored_translations(self, record) -> StoredTranslations | None:
        return _cache._get_stored_translations(self, record)
    def translation_lang(self, env):
        return _cache.translation_lang(self, env)
    def _get_cache_impl(self, env):
        return _cache._get_cache_impl(self, env)
    def _cache_missing_ids(self, records):
        return _cache._cache_missing_ids(self, records)
    def _to_prefetch(self, record):
        return _cache._to_prefetch(self, record)
    def _insert_cache(self, records, values):
        return _cache._insert_cache(self, records, values)
    def _update_cache(self, records, cache_value, dirty=False):
        return _cache._update_cache(self, records, cache_value, dirty)
    def _inverse_related(self, records):
        return _write._inverse_related(self, records)
    def write(self, records, value):
        return _write.write(self, records, value)
    def to_sql(self, table: TableSQL) -> SQL:
        return _query.to_sql(self, table)
    def expression_getter(self, field_expr):
        return _query.expression_getter(self, field_expr)
    def condition_to_sql(self, table: TableSQL, field_expr: str, operator: str, value) -> SQL:
        return _query.condition_to_sql(self, table, field_expr, operator, value)


# the delegated methods of the class, and the modules that use the class: at the end, they import this module
from . import cache as _cache, write as _write, query as _query  # noqa: E402
