# Part of Odoo. See LICENSE file for full copyright and licensing details.
"""Field translations: reading and updating the translations of the fields."""

from __future__ import annotations

import re
import typing

import psycopg2.errors
import psycopg2.extensions

from odoo.exceptions import MissingError


from odoo.orm.fields.textual import StoredTranslations
from collections.abc import Callable
from odoo.exceptions import UserError
from odoo.tools.text.translate import _


if typing.TYPE_CHECKING:
    from collections.abc import Collection, Sequence
    from odoo.orm.core.types import ValuesType


regex_order_part_read_group = re.compile(r"""
    \s*
    (?P<term>(?P<field>[a-z0-9_]+)(\.([\w\.]+))?(:(?P<func>[a-z_]+))?)
    (\s+(?P<direction>desc|asc))?
    (\s+(?P<nulls>nulls\ first|nulls\ last))?
    \s*
""", re.IGNORECASE | re.VERBOSE)
regex_field_agg = re.compile(r'(\w+)(?::(\w+)(?:\((\w+)\))?)?')  # For read_group
regex_read_group_spec = re.compile(r'(\w+)(\.([\w\.]+))?(?::(\w+))?$')  # For _read_group

INSERT_BATCH_SIZE = 100
UPDATE_BATCH_SIZE = 100
SQL_DEFAULT = psycopg2.extensions.AsIs("DEFAULT")


def get_field_translations(self, field_name: str, langs: Collection[str] | None=None) -> tuple[list[dict[str, str]], dict[str, typing.Any]]:
    self.ensure_one()
    field = self._fields[field_name]
    # We don't forbid reading inactive/non-existing languages,
    langs = set(langs or [l[0] for l in self.env['res.lang'].get_installed()])
    self_lang = self.with_context(check_translations=True, prefetch_langs=True)
    val_en = self_lang.with_context(lang='en_US')[field_name]
    if not field.translate:
        translations = []
    elif field.translate is True:
        translations = [{
            'lang': lang,
            'source': val_en,
            'value': self_lang.with_context(lang=lang)[field_name]
        } for lang in langs]
    else:
        translation_dictionary = StoredTranslations._get_translation_dictionary(
            field, val_en, {lang: self_lang.with_context(lang=lang)[field_name] for lang in langs}
        )
        translations = [{
            'lang': lang,
            'source': term_en,
            'value': term_lang if term_lang != term_en else ''
        } for term_en, translations in translation_dictionary.items()
            for lang, term_lang in translations.items()]
    context = {}
    context['translation_type'] = 'text' if field.type in ['text', 'html'] else 'char'
    context['translation_show_source'] = callable(field.translate)

    return translations, context


def _get_base_lang(self) -> str:
    self.ensure_one()
    return 'en_US'


def _read_format(self, fnames: Sequence[str], load: str='_classic_read') -> list[ValuesType]:
    data = [(record, {'id': record.id}) for record in self]
    use_display_name = (load == '_classic_read')
    for name in fnames:
        field = self._fields[name]
        if field.type == 'properties':
            values_list = []
            records = []
            for record, vals in data:
                try:
                    values_list.append(record[name])
                    records.append(record.id)
                except MissingError:
                    vals.clear()

            results = field.convert_to_read_multi(values_list, self.browse(records))
            for record_read_vals, convert_result in zip(data, results):
                record_read_vals[1][name] = convert_result
            continue

        convert = field.convert_to_read
        if field.type == 'binary' and load == 'web':
            def binary_convert(value, record, use_display_name):
                if not value:
                    return False
                res = {}
                # Include the file name
                filename = value.filename
                if filename and filename != field.name:
                    res['filename'] = filename
                # For NewIds, always include the content
                include_content = not any(record._ids)
                if include_content:
                    res['content'] = value.to_base64()
                res['size'] = value.size
                res['checksum'] = value.checksum
                return res
            convert = binary_convert

        for record, vals in data:
            # missing records have their vals empty
            if not vals:
                continue
            try:
                vals[name] = convert(record[name], record, use_display_name)
            except MissingError:
                vals.clear()
    result = [vals for record, vals in data if vals]

    return result


def update_field_translations(self, field_name: str, translations: dict[str, str | typing.Literal[False] | dict[str, str]], source_lang: str='') -> bool:
    return self._update_field_translations(field_name, translations, source_lang=source_lang)


def _update_field_translations(self, field_name: str, translations: dict[str, str | typing.Literal[False] | dict[str, str]], digest: Callable[[str], str] | None=None, source_lang: str='') -> bool:
    self.ensure_one()

    self.check_access('write')
    field = self._fields[field_name]
    self.check_field_access(field, 'write')

    valid_langs = set(code for code, _ in self.env['res.lang'].get_installed()) | {'en_US'}
    source_lang = source_lang or 'en_US'
    missing_langs = (set(translations) | {source_lang}) - valid_langs
    if missing_langs:
        raise UserError(
            _("The following languages are not activated: %(missing_names)s",
            missing_names=', '.join(missing_langs))
        )

    if not field.translate:
        return False  # or raise error

    if not field.store and not field.related and field.compute:
        # a non-related non-stored computed field cannot be translated, even if it has inverse function
        return False

    # Strictly speaking, a translated related/computed field cannot be stored
    # because the compute function only support one language
    # `not field.store` is a redundant logic.
    # But some developers store translated related fields.
    # In these cases, only all translations of the first stored translation field will be updated
    # For other stored related translated field, the translation for the flush language will be updated
    if field.related and not field.store:
        related_path, field_name = field.related.rsplit(".", 1)
        return self.mapped(related_path)._update_field_translations(field_name, translations, digest)

    if field.translate is True:
        # falsy values (except emtpy str) are used to void the corresponding translation
        if any(translation and not isinstance(translation, str) for translation in translations.values()):
            raise UserError(_("Translations for model translated fields only accept falsy values and str"))
        value_en = translations.get('en_US', True)
        if not value_en and value_en != '':
            translations.pop('en_US')
        if not translations:
            return False

        drop_langs = {lang for lang, value in translations.items() if not isinstance(value, str)}
        translations = {lang: value for lang, value in translations.items() if lang not in drop_langs}
        if drop_langs:
            stored_translations = self._get_stored_translations(field_name)
            if field.type == 'html':
                translations = {lang: field._validated_cache_value(value, self.env) for lang, value in translations.items()}
            if stored_translations is None:
                if not translations:
                    return False
                write_value = StoredTranslations({
                    'en_US': translations.get(self.env.lang or 'en_US', next(iter(translations.values()))),
                    **translations,
                })
            else:
                write_value = StoredTranslations({
                    **{lang: value for lang, value in stored_translations.items() if lang not in drop_langs},
                    **translations,
                })
        else:
            write_value = translations
        self[field_name] = write_value
        return True
    else:
        stored_translations = self._get_stored_translations(field_name)
        if not stored_translations:
            return False
        write_value = stored_translations.translated(
            self.env, field, source_lang, translations, digest=digest,
            delay_translations=bool(self.env.context.get('delay_translations')),
        )
        self[field_name] = write_value
    return True


def _get_stored_translations(self, field_name: str) -> StoredTranslations | None:
    self.ensure_one()
    field = self._fields[field_name]
    record = self
    while field.related and not field.store:
        record = record.mapped(field.related.rsplit('.', 1)[0])[:1]
        if not record:
            return None
        field = field.related_field
    return field._get_stored_translations(record)
