"""The stored translations of the fields: the translations per language and the parsed translations."""

from __future__ import annotations

import logging
import typing
from collections import defaultdict
from difflib import get_close_matches
from odoo.exceptions import ValidationError

if typing.TYPE_CHECKING:
    from collections.abc import Callable
    from typing import Any, Literal
    from odoo.api import Environment
    from odoo.orm.fields.textual import BaseString
    from odoo.orm.models import BaseModel


_logger = logging.getLogger('odoo.tools.text.translate')


class StoredTranslations(dict):
    """Dictionary-based cache value that stores the raw JSON translations from the database.

    This provides easier write operations at the cost of slower cache reads, as it implements
    custom fallback logic in `__getitem__`. The `'en_US'` key is expected to be present as the
    default fallback language.
    """
    __slots__ = ()

    @staticmethod
    def fallback_langs(lang: str) -> tuple[str, ...]:
        if lang == '_en_US':
            return '_en_US', 'en_US'
        if lang == 'en_US':
            return ('en_US',)
        if lang.startswith('_'):
            return lang, lang[1:], '_en_US', 'en_US'
        return lang, 'en_US'

    @staticmethod
    def _get_translation_dictionary(field: BaseString, from_lang_value, to_lang_values):
        """ Build a dictionary from terms in from_lang_value to terms in to_lang_values

        :param str from_lang_value: from xml/html
        :param dict to_lang_values: {lang: lang_value}

        :return: {from_lang_term: {lang: lang_term}}
        :rtype: dict
        """
        if not isinstance(from_lang_value, str):
            return defaultdict(lambda: defaultdict(dict))
        if callable(field.translate):
            from_lang_terms = ParsedTranslation(field, from_lang_value).terms if from_lang_value else []
        else:
            # Ensure translation terms are stringified.
            # Double quotes inside Markup are not escaped when the value is used as a polib.POEntry msgid.
            from_lang_terms = [str(from_lang_value)]
        dictionary = defaultdict(lambda: defaultdict(dict))
        if not from_lang_terms:
            return dictionary
        dictionary.update({from_lang_term: defaultdict(dict) for from_lang_term in from_lang_terms})

        for lang, to_lang_value in to_lang_values.items():
            if callable(field.translate):
                to_lang_terms = ParsedTranslation(field, to_lang_value).terms if to_lang_value else []
            else:
                to_lang_terms = [str(to_lang_value)] if isinstance(to_lang_value, str) else []
            if len(from_lang_terms) != len(to_lang_terms):
                for from_lang_term in from_lang_terms:
                    dictionary[from_lang_term][lang] = from_lang_term
            else:
                for from_lang_term, to_lang_term in zip(from_lang_terms, to_lang_terms):
                    dictionary[from_lang_term][lang] = to_lang_term
        return dictionary

    def __getitem__(self, key):
        """ Retrieve the translation for the specified language code with automatic fallback.

        :param key: Language code (non-empty string).
                    Fallback logic:
                    - For normal language codes (e.g., 'fr_FR'):
                    Tries: key -> 'en_US'
                    - For technical language codes (prefixed with '_', e.g., '_fr_FR'):
                    Tries: key -> key[1:] -> '_en_US' -> 'en_US'

                    Note: This fallback behavior is consistent with ``field.to_sql``
                    when ``prefetch_lang=False`` for translated fields

        :return: The translation value for the language code.
        """
        # Direct dict method calls for performance optimization (bypass super())
        if (res := dict.get(self, key)) is not None:
            return res
        if key[0] == '_':
            if (res := dict.get(self, key[1:])) is not None:
                return res
            if (res := dict.get(self, '_en_US')) is not None:
                return res
        try:
            return dict.__getitem__(self, 'en_US')
        except KeyError:
            _logger.warning("StoredTranslations %s has no translation for 'en_US'", dict(self))
            # return the same behavior as ``field.to_sql`` when ``prefetch_lang=False``
            # if 'en_US' is missing for a NOT NULL value
            return None

    def __contains__(self, key) -> bool:
        return True

    def copy(self) -> StoredTranslations:
        return StoredTranslations(self)

    def get(self, key, default=None):
        return self[key]

    def normalize(self, env: Environment, field: BaseString) -> StoredTranslations | None:
        """Check and auto fix issues for stored translations and return a new StoredTranslations instance or None"""
        return self._validate(env, field, auto_fix=True)

    def validate(self, env: Environment, field: BaseString) -> None:
        """Validate stored translations against soft constraints for the translated field"""
        self._validate(env, field, auto_fix=False)

    def _validate(self, env: Environment, field: BaseString, *, check_structure: bool = True, auto_fix: bool = False) -> StoredTranslations | None:
        """Validate stored translations against soft constraints for the translated field"""
        fixed_self = self.copy()
        issues = []

        active_langs = env['res.lang']._get_active_by('code')
        valid_langs = active_langs.keys() | {'en_US'}
        if callable(field.translate):
            valid_langs |= {'_' + lang for lang in valid_langs}

        # clean up invalid languages and drop None values
        for k, v in self.items():
            if k not in valid_langs:
                if not auto_fix:
                    raise ValidationError(env._("Translations %(translations)s for field %(field)s has invalid language '%(language)s'", translations=self, field=field, language=k))
                # Unlike other issues (usually coding errors), invalid languages are typically
                # caused by deactivating languages in res.lang; clean them up silently.
                fixed_self.pop(k)
            elif v is None:
                if not auto_fix:
                    raise ValidationError(env._("Translations %(translations)s for field %(field)s has None value for language '%(language)s'", translations=self, field=field, language=k))
                issues.append(f"It has None value for language '{k}'.")
                fixed_self.pop(k)

        # en_US must exist
        if not dict.__contains__(fixed_self, 'en_US'):  # noqa: PLC2801
            if not auto_fix:
                raise ValidationError(env._("Translations %(translations)s for field %(field)s must have 'en_US'", translations=self, field=field))
            issues.append("It has no 'en_US'.")
            if not fixed_self:
                return None
            fixed_self['en_US'] = next(iter(fixed_self.values()))

        # check technical languages which start with '_'
        assert field.translate
        if callable(field.translate):
            for k, v in list(fixed_self.items()):
                if k.startswith('_') and not dict.__contains__(fixed_self, k[1:]):  # noqa: PLC2801
                    if not auto_fix:
                        raise ValidationError(env._("Translations %(translations)s for field %(field)s has technical language %(technical_language)s but not corresponding language '%(language)s'", translations=self, field=field, technical_language=k, language=k[1:]))
                    issues.append(f"It has technical language '{k}' but not corresponding language '{k[1:]}'.")
                    fixed_self[k[1:]] = fixed_self['en_US']

        if check_structure and callable(field.translate):
            translations = {k: fixed_self['_' + k] for k in fixed_self if not k.startswith('_')}
            # all translations must share the same structure
            if len({*translations.values()}) > 1:
                translation_en = translations['en_US']
                structure_en = ParsedTranslation(field, translation_en).structure
                for k, v in translations.items():
                    if v != translation_en and ParsedTranslation(field, v).structure != structure_en:
                        if not auto_fix:
                            raise ValidationError(env._("Translations %(translations)s for field %(field)s have different structures", translations=self, field=field))
                        issues.append(f"Its translation for language '{k}' has different structure from 'en_US.'")
                        fixed_self.pop(k, None)
                        fixed_self.pop('_' + k, None)

        if issues:
            _logger.info(
                "Auto fix StoredTranslations for field %s from %s to %s because:\n%s",
                field, self, fixed_self, ",\n".join(issues)
            )

        return fixed_self

    def written(self, env: Environment, field: BaseString, translation_dict: dict[str, ParsedTranslation], *, adapt_close_terms: bool = False, delay_translations: bool = False) -> StoredTranslations | None:
        """ Apply written translations and build a new stored mapping.

        :param env: Current Odoo environment, used for validation and
                    language-aware errors.
        :param field: A model_terms translated field (``callable(field.translate)``).
        :param translation_dict: Mapping ``{lang_code: ParsedTranslation}`` for
                                 languages explicitly written in this update.
        :param adapt_close_terms: If ``True`` and supported by
                                  ``field.translate.term_adapter``, remap old
                                  term translations to close new terms.
        :param delay_translations: If ``True``, keep current non-written
                                   language values and store recomputed values
                                   in technical keys (``_lang``). If ``False``,
                                   write recomputed values directly.
        :return: A new validated ``StoredTranslations`` result, or ``None`` when no
                 valid translation can be kept.
        """
        assert callable(field.translate)  # model translated field is not supported
        valid_self = self._validate(env, field, check_structure=False, auto_fix=True)

        if not translation_dict:
            return valid_self

        if not valid_self:
            return StoredTranslations({
                'en_US': next(iter(translation_dict.values())).value,
                **{k: v.value for k, v in translation_dict.items()},
            })

        # assert all(not key.startswith('_') for key in translation_dict)
        # assert len({v.structure for v in translation_dict.values())}) <= 1

        # use the first matched language as base language if its written translation is the same as before
        # otherwise, use the first write language as the base language
        # in practice, it is always recommended to use the env.lang value as the first key of translation_dict
        translate_terms_only = False
        base_lang = next(
            (k for k, v in translation_dict.items() if v.value == valid_self['_' + k] and (translate_terms_only := True)),
            next(iter(translation_dict))
        )

        if translate_terms_only:
            # Base language value is unchanged; update only term translations for non-base languages.
            for k, v in translation_dict.items():
                valid_self[k] = v.value  # update new translations
                valid_self.pop('_' + k, None)  # drop old technical sycnhronized translations for updated languages
            return valid_self

        base_value = translation_dict[base_lang].value
        base_terms = translation_dict[base_lang].terms
        base_terms_set = set(base_terms)
        other_old_translations = {
            k: valid_self['_' + k]
            for k in valid_self
            if not k.startswith('_')
            and k not in translation_dict
        }

        # parse the translation term mapping for old non-update translations
        translation_dictionary = StoredTranslations._get_translation_dictionary(field, valid_self['_' + base_lang], other_old_translations)

        # best effort to migrate old translation terms to new close translation terms
        get_text_content = field.translate.get_text_content if hasattr(field.translate, 'get_text_content') else lambda term: term
        is_text = field.translate.is_text if hasattr(field.translate, 'is_text') else lambda term: True
        term_adapter = field.translate.term_adapter if adapt_close_terms and hasattr(field.translate, 'term_adapter') else None
        text2terms = defaultdict(list[str])
        for term in base_terms:
            if term_text := get_text_content(term):
                text2terms[term_text].append(term)
        for old_term in list(translation_dictionary):
            if old_term in base_terms_set:
                continue
            old_term_text = get_text_content(old_term)
            # Find the new base term text which is most similar to the old term's text (fuzzy match, cutoff 0.9)
            closest_text = next(iter(get_close_matches(old_term_text, text2terms, n=1, cutoff=0.9)), None)
            if closest_text is None:
                continue
            # Among new base terms sharing that text, find the specific new base term closest to the old term
            closest_term = get_close_matches(old_term, text2terms[closest_text], n=1, cutoff=0)[0]
            if closest_term in translation_dictionary:
                continue
            old_is_text = is_text(old_term)
            closest_is_text = is_text(closest_term)
            if not old_is_text and closest_is_text:
                # Don't migrate translations for a old non-text term to a new text term
                # in case the new text term is used for TRANSLATED_ATTRS
                continue
            if not closest_is_text and term_adapter:
                adapter = term_adapter(closest_term)
                if adapter(old_term) is None:
                    # Don't migrate if old term and closest_term have different structures when adapter is applied
                    continue
                translation_dictionary[closest_term] = {k: adapter(v) for k, v in translation_dictionary.pop(old_term).items()}
            else:
                translation_dictionary[closest_term] = translation_dictionary.pop(old_term)

        # use the old translation mapping to get new translations for the not directly updated languages
        other_new_translations = {
            l: field.translate(lambda term: translation_dictionary.get(term, {l: None})[l], base_value)
            for l in other_old_translations
        }

        # update self for not directly updated languages
        if delay_translations:
            for k, v in other_new_translations.items():
                if v == valid_self[k]:
                    valid_self.pop('_' + k, None)
                else:
                    valid_self['_' + k] = v
        else:
            for k, v in other_new_translations.items():
                valid_self.pop('_' + k, None)
                valid_self[k] = other_new_translations[k]

        # update self for directly updated languages
        for k, v in translation_dict.items():
            # remove old technical synchronized translations
            valid_self.pop('_' + k, None)
            # use new updated translations
            valid_self[k] = v.value
        return valid_self

    def translated(
        self,
        env: Environment,
        field: BaseString,
        source_lang: str,
        term_updates: dict[str, dict[str, str]],
        *,
        digest: Callable[[str], str] | None = None,
        overwrite: bool = True,
        delay_translations: bool = False,
    ) -> StoredTranslations | None:
        """ Apply term-level translations and build a new stored mapping.

        :param env: Current Odoo environment, used for validation and
                    language-aware errors.
        :param field: A model_terms translated field (``callable(field.translate)``).
        :param source_lang: Language of the source terms in ``term_updates``.
        :param term_updates: Mapping ``{lang_code: {source_term: translated_term}}``
                             for languages explicitly updated in this call.
        :param digest: Optional digest function for source terms in ``term_updates``
                       when the caller sends digested source keys.
        :param overwrite: Controls merge priority between incoming ``term_updates`` and
                          the prior term mappings derived from the stored field value.
                          When ``True`` (default), incoming updates take priority; when
                          ``False``, prior mappings take priority. Prior mappings are those
                          where the stored term differs from the source term (``term != src``).
                          see ``TestStoredTranslations.test_translated_overwrite_false`` for more details.
        :param delay_translations: If ``True``, keep current non-updated language
                                   values and store recomputed values in technical
                                   keys (``_lang``). If ``False``, write recomputed
                                   values directly.
        :return: A new validated ``StoredTranslations`` result, or ``None`` when no
                 valid translation can be kept.
        """
        assert callable(field.translate)
        valid_self = self._validate(env, field, check_structure=False, auto_fix=True)
        if not valid_self:
            return None

        # For updated languages, use the latest synchronized value as base.
        if not delay_translations:
            for lang in term_updates:
                if dict.__contains__(valid_self, f'_{lang}'):  # noqa: PLC2801
                    valid_self[lang] = valid_self.pop(f'_{lang}')

        term_updates = {lang: src2term for lang, src2term in term_updates.items() if src2term}
        if not term_updates:
            return valid_self

        old_source_lang_value = valid_self['_' + source_lang]
        old_values_to_translate = {
            lang: value
            for lang in term_updates
            if (value := valid_self['_' + lang]) != old_source_lang_value
        }
        # {source_term: {lang: translated_term}}
        old_translation_dictionary = StoredTranslations._get_translation_dictionary(field, old_source_lang_value, old_values_to_translate)

        if digest:
            # replace digested old source terms with real old source terms
            digested2term = {
                digest(old_term): old_term
                for old_term in old_translation_dictionary
            }
            term_updates = {
                lang: {
                    digested2term[src]: term
                    for src, term in src2term.items()
                    if src in digested2term
                }
                for lang, src2term in term_updates.items()
            }

        for lang, src2term in term_updates.items():
            old_src2term = {src: term for src, lang2term in old_translation_dictionary.items() if (term := lang2term.get(lang)) and term != src}
            new_src2term = {**old_src2term, **src2term} if overwrite else {**src2term, **old_src2term}
            translation = field.translate(new_src2term.get, old_source_lang_value)
            if field.type == 'html':
                # a hack to sanitize html
                translation = field._validated_cache_value(translation, env)
            if delay_translations:
                valid_self['_' + lang] = translation
                valid_self.setdefault(lang, valid_self['en_US'])
            else:
                valid_self[lang] = translation
        return valid_self

    def extract_term_translations(self, env: Environment, field: BaseString, source_lang: str, target_langs: set[str] | None = None, *, include_identical: bool = False) -> dict[str, dict[str, str]]:
        """ Extract per-language term mappings from stored model_terms translations.

        :param env: Odoo environment
        :param field: A model_terms translated field (``callable(field.translate)``).
        :param source_lang: Language of the source terms to extract against
        :param target_langs: if provided, restrict output to these language codes
        :param include_identical: if True, also keep terms where translated_term == source_term
        :return: the terms mapping for each target language {lang: {src_term: translated_term}}
        """
        assert callable(field.translate)
        valid_self = self._validate(env, field, check_structure=False, auto_fix=True)
        if not valid_self:
            return {}

        source_value = valid_self['_' + source_lang]

        target_lang_values = {
            lang: value
            for lang in valid_self
            if not lang.startswith('_')
            and lang != source_lang and (target_langs is None or lang in target_langs)
            and (value := valid_self['_' + lang]) != source_value
        }
        if not target_lang_values and not include_identical:
            return {}

        # {source_term: {lang: translated_term}}
        translation_dictionary = StoredTranslations._get_translation_dictionary(field, source_value, target_lang_values)

        # Invert to {lang: {source_term: translated_term}}
        result: dict[str, dict[str, str]] = {}
        for source_term, lang2term in translation_dictionary.items():
            for lang, translated_term in lang2term.items():
                if include_identical or source_term != translated_term:
                    result.setdefault(lang, {})[source_term] = translated_term

        if include_identical:
            for lang in env['res.lang']._get_active_by('code') if target_langs is None else target_langs:
                if lang not in result:
                    result[lang] = {source_term: source_term for source_term in translation_dictionary}

        return result


class ParsedTranslation:
    def __init__(self, field: BaseString, value: str):
        assert isinstance(value, str)
        self.value: str = value

        assert callable(field.translate)
        self.terms: list[str] = []

        def translate_func(term):
            self.terms.append(term)
            return 'X'

        self.structure = field.translate(translate_func, value)


def adapt_translated_field_value(
    env: Environment,
    field: BaseString,
    val: StoredTranslations | dict[str, str] | str | Literal[False] | None,
    adapter: Callable[[str, str], str],
) -> StoredTranslations | dict[str, str] | str | Literal[False] | None:
    """Apply an adapter to a translated field value, handling all supported value formats.

    Translated fields accept either a plain string (single language) or a dict mapping
    language codes to translated strings. This function applies the adapter to each
    value, preserving None and False as-is.

    :param env: the Odoo environment
    :param field: the translated field
    :param val: the value to adapt; can be a dict {lang: value}, a plain string,
                or None/False
    :param adapter: callable(lang, value) -> str; receives language code and value,
                    returns the adapted value for each translation
    :return: the adapted value in the same format as ``val``
    """
    if val is None or val is False:
        return val
    if not isinstance(val, dict):
        return adapter(env.lang or 'en_US', val)
    assert field.translate
    adapted = {k: adapter(k, v) for k, v in val.items() if k == 'en_US' or env['res.lang']._lang_get(k)}
    if isinstance(val, StoredTranslations):
        model = env[field.model_name]
        return StoredTranslations({
            k: cache_v
            for k, v in adapted.items()
            if (cache_v := field.convert_to_cache(v, model)) is not None
        })
    return adapted


def mark_as_copy(field_name: str) -> Callable[[BaseModel], Any]:
    """Factory for a :attr:`~odoo.fields.Field.copy` callable that appends `` (copy)``.

    Usage::

        name = fields.Char(..., copy=mark_as_copy('name'))
    """
    def _mark_as_copy(record):
        field = record._fields[field_name]
        assert field.type == 'char'
        env = record.env
        assert not callable(field.translate)
        if field.translate:
            translations = record._get_stored_translations(field_name)
            if not translations:
                return False
            return adapt_translated_field_value(
                env, field, translations,
                lambda lang, v: record.with_context(lang=lang).env._('%s (copy)', v),
            )
        if record[field_name] is False:
            return record[field_name]
        return env._('%s (copy)', record[field_name])

    return _mark_as_copy
