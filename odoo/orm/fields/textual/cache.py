"""The cache of the translated values: the stored translations of the records and the values per language."""

from __future__ import annotations

import collections.abc
import typing
from odoo.tools.misc import SENTINEL
from odoo.tools.text.translate import StoredTranslations
from odoo.orm.core.utils import expand_ids

if typing.TYPE_CHECKING:
    pass

from .base import BaseString

def _validated_cache_value(self, value: str, env) -> str:
    if callable(self.translate):
        # auto fix broken value
        value = self.translate(lambda t: None, value)  # pylint: disable=not-callable
    return value


def _get_stored_translations(self, record) -> StoredTranslations | None:
    """
    : return: {'en_US': 'value_en_US', 'fr_FR': 'French'}
    """
    assert self.translate and self.store, f"Field {self} should be a translated and stored to get the translations"
    if self.compute and self.store:
        self.recompute(record)
    field_cache = record.env.transaction.field_data[self]
    value = field_cache.get(record.id, SENTINEL)
    if value is None:
        return None
    if isinstance(value, StoredTranslations):
        return value.copy()
    complete_translations_types = (type(None), StoredTranslations)
    records_to_fetch = record.browse(
        id_ for id_ in expand_ids(record.id, record._prefetch_ids)
        if not isinstance(field_cache.get(id_, SENTINEL), complete_translations_types)
    )
    # refetch field values for all languages
    records_to_fetch.invalidate_recordset([self.name])
    records_to_fetch.with_context(prefetch_langs=True).fetch([self.name])
    value = field_cache.get(record.id, SENTINEL)
    if isinstance(value, StoredTranslations):
        return value.copy()
    # column value is NULL or the record row doesn't exist in database
    return None


def translation_lang(self, env):
    return (env.lang or 'en_US') if self.translate is True else env._lang


def _get_cache_impl(self, env):
    cache = super(BaseString, self)._get_cache_impl(env)
    if not self.translate or env.context.get('prefetch_langs'):
        return cache
    lang = self.translation_lang(env)
    return LangProxyDict(self, cache, lang)


def _cache_missing_ids(self, records):
    if self.translate and records.env.context.get('prefetch_langs'):
        # we always need to fetch the current language in the cache
        records = records.with_context(prefetch_langs=False)
    return super(BaseString, self)._cache_missing_ids(records)


def _to_prefetch(self, record):
    if self.translate and record.env.context.get('prefetch_langs'):
        # we always need to fetch the current language in the cache
        return super(BaseString, self)._to_prefetch(record.with_context(prefetch_langs=False)).with_env(record.env)
    return super(BaseString, self)._to_prefetch(record)


def _insert_cache(self, records, values):
    if not self.translate:
        super(BaseString, self)._insert_cache(records, values)
        return

    assert self not in records.env._field_depends_context, f"translated field {self} cannot depend on context"
    env = records.env
    field_cache = env.transaction.field_data[self]
    if env.context.get('prefetch_langs'):
        for id_, val in zip(records._ids, values):
            if val is None:
                field_cache.setdefault(id_, None)
            else:
                field_cache[id_] = StoredTranslations(val)
    else:
        lang = self.translation_lang(env)
        for id_, val in zip(records._ids, values):
            if val is None:
                field_cache.setdefault(id_, None)
            else:
                cache_value = field_cache.setdefault(id_, {})
                if cache_value is not None and lang not in cache_value:
                    # use __contains__ instead of setdefault to avoid contaminating StoredTranslations instances
                    cache_value[lang] = val


def _update_cache(self, records, cache_value, dirty=False):
    if self.translate and cache_value is not None:
        is_translation_dict = isinstance(cache_value, dict)
        records = records.with_context(prefetch_langs=is_translation_dict)
        if is_translation_dict and len(records) > 1:
            # new dict for each record
            for record in records:
                super(BaseString, self)._update_cache(record, cache_value.copy(), dirty)
            return
    super(BaseString, self)._update_cache(records, cache_value, dirty)


class LangProxyDict(collections.abc.MutableMapping):
    """A view on a dict[id, dict[lang, value]] that maps id to value given a
    fixed language."""
    __slots__ = ('_cache', '_field', '_lang')

    def __init__(self, field: BaseString, cache: dict, lang: str):
        super().__init__()
        self._field = field
        self._cache = cache
        self._lang = lang

    def get(self, key, default=None):
        # just for performance
        vals = self._cache.get(key, SENTINEL)
        if vals is SENTINEL:
            return default
        if vals is None:
            return None
        if not (self._field.compute or (self._field.store and (key or key.origin))):
            # the field's value is neither computed, nor in database
            # (non-stored field or new record without origin), so fallback on
            # its 'en_US' value in cache
            return vals.get(self._lang, vals.get('en_US', default))
        return vals.get(self._lang, default)

    def __getitem__(self, key):
        vals = self._cache[key]
        if vals is None:
            return None
        if not (self._field.compute or (self._field.store and (key or key.origin))):
            # the field's value is neither computed, nor in database
            # (non-stored field or new record without origin), so fallback on
            # its 'en_US' value in cache
            return vals.get(self._lang, vals.get('en_US'))
        return vals[self._lang]

    def __setitem__(self, key, value):
        if value is None:
            self._cache[key] = None
            return
        vals = self._cache.get(key)
        if vals is None:
            # key is not in cache, or {key: None} is in cache
            self._cache[key] = vals = {self._lang: value}
        else:
            vals[self._lang] = value
        if not (self._field.compute or (self._field.store and (key or key.origin))):
            # the field's value is neither computed, nor in database
            # (non-stored field or new record without origin), so the cache
            # must contain the fallback 'en_US' value for other languages
            vals.setdefault('en_US', value)

    def __delitem__(self, key):
        vals = self._cache.get(key)
        if vals:
            vals.pop(self._lang, None)

    def __iter__(self):
        for key, vals in self._cache.items():
            if vals is None or self._lang in vals:
                yield key

    def __len__(self):
        return sum(1 for _ in self)

    def clear(self):
        for vals in self._cache.values():
            if vals:
                vals.pop(self._lang, None)

    def __repr__(self):
        return f"<LangProxyDict lang={self._lang!r} size={len(self._cache)} at {hex(id(self))}>"
