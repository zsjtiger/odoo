"""The writes of the string fields: the writes of the translations and the inverse of the related fields."""

from __future__ import annotations

import typing
from odoo.exceptions import ValidationError
from odoo.tools.misc import SENTINEL
from odoo.tools.text.translate import StoredTranslations, ParsedTranslation

if typing.TYPE_CHECKING:
    pass

from .base import BaseString

def _inverse_related(self, records):
    if not self.translate:
        return super(BaseString, self)._inverse_related(records)
    # store record values, otherwise they may be lost by cache invalidation!
    field_cache = records.env.transaction.field_data[self]
    record_value = {
        record: field_cache.get(record.id, record[self.name])
        for record in records
    }
    path = self.related.split('.')[:-1]
    field = self.related_field
    for record in records:
        target = record
        for name in path:
            target = target[name][:1]
        if target and bool(target.id) == bool(record.id):
            target[field.name] = record_value[record]


def write(self, records, value):
    if not self.translate or value is False or value is None:
        super(BaseString, self).write(records, value)
        return

    records.env.remove_to_compute(self, records)
    lang = records.env.lang or 'en_US'
    if isinstance(value, StoredTranslations):
        assert any(records._ids)
        cache_value = self.convert_to_cache(value, records)
        records = self._filter_not_equal(records.with_context(prefetch_langs=True), cache_value)
        self._update_cache(records.with_context(prefetch_langs=True), cache_value, dirty=bool(self.store))
        return
    elif isinstance(value, dict):
        cache_value_dict = self.convert_to_cache(value, records)
        if not cache_value_dict:
            return
        # force update all records
    else:
        cache_value = self.convert_to_cache(value, records)
        cache_value_dict = {self.translation_lang(records.env): cache_value}
        records = self._filter_not_equal(records, cache_value)
    if not records:
        return

    field_cache = self._get_cache(records.env)
    dirty_ids = records.env._field_dirty.get(self, ())

    # flush dirty None values which drop all translations
    dirty_records = records.filtered(lambda rec: rec.id in dirty_ids)
    if any(field_cache.get(record_id, SENTINEL) is None for record_id in dirty_records._ids):
        dirty_records.flush_recordset([self.name])

    dirty = self.store and any(records._ids)
    # not dirty fields
    if not dirty:
        if self.inverse and any(records._ids):
            # only keep the cache_value_dict which will be used in inverse methods
            self._update_cache(records.with_context(prefetch_langs=True), cache_value_dict, dirty=False)
        else:
            # keep as many cache values as possible
            for k, v in cache_value_dict.items():
                self._update_cache(records.with_context(lang=k, prefetch_langs=False), v, dirty=False)
        return

    base_lang = lang if lang in cache_value_dict else next(iter(cache_value_dict))

    # model translation
    if not callable(self.translate):
        # invalidate clean fields because them may contain fallback value
        clean_records = records.filtered(lambda rec: rec.id not in dirty_ids)
        clean_records.invalidate_recordset([self.name])
        if not records.env['res.lang']._lang_get('en_US') and 'en_US' not in cache_value_dict:
            # if 'en_US' is not active, we always write en_US to make sure value_en is meaningful
            cache_value_dict['en_US'] = cache_value_dict[base_lang]
        for lang_, value_ in cache_value_dict.items():
            # updating language by language instead of replacing the cache value
            # to avoid losing translation for dirty records
            self._update_cache(records.with_context(lang=lang_, prefetch_langs=False), value_, dirty=True)
        return

    # model term translation
    parsed_translation_dict: dict[str, ParsedTranslation]
    # give the current language value a priority to be the base language during ``StoredTranslations.written``
    parsed_translation_dict = {lang: None} if lang in cache_value_dict else {}
    parsed_translation_dict.update(
        {k: ParsedTranslation(self, v)
        for k, v in cache_value_dict.items()
    })
    if len({v.structure for v in parsed_translation_dict.values()}) > 1:
        # check consistency for non translatable data
        raise ValidationError(records.env._(
            "The non translatable content of the written value are not consistent: %s", value
        ))
    if not records.env['res.lang']._lang_get('en_US'):
        parsed_translation_dict['en_US'] = parsed_translation_dict[base_lang]

    if not next(iter(parsed_translation_dict.values())).terms:
        # directly update the cache when no term needs to be translated
        self._update_cache(
            records.with_context(prefetch_langs=True),
            StoredTranslations({**cache_value_dict, 'en_US': cache_value_dict[base_lang]}),
            dirty=True
        )
        return

    delay_translations = records.env.context.get('delay_translations')
    adapt_close_terms = records.env.context.get("install_mode") and lang == 'en_US'
    for record in records.with_context(prefetch_langs=True):
        if not (stored_translations_data := self._get_stored_translations(record)):
            # directly update the cache when no translation existed before
            self._update_cache(record, StoredTranslations({**cache_value_dict, 'en_US': cache_value_dict[base_lang]}), dirty=True)
            continue

        stored_translations = stored_translations_data.written(
            records.env, self, parsed_translation_dict,
            adapt_close_terms=adapt_close_terms, delay_translations=delay_translations
        )
        if stored_translations != stored_translations_data:
            self._update_cache(record, stored_translations, dirty=True)
