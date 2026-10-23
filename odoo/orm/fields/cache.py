"""Cache of the field values in the environments."""

from __future__ import annotations

import collections
import logging
import typing
from odoo.tools.misc import SENTINEL
from odoo.orm.core.utils import expand_ids

if typing.TYPE_CHECKING:
    from collections.abc import Collection, Iterable, Iterator, MutableMapping
    from odoo.orm.models.environments import Environment
    from odoo.orm.core.identifiers import IdType
    from odoo.orm.core.types import BaseModel, ModelType


_logger = logging.getLogger('odoo.fields')


def _get_cache(self, env: Environment) -> MutableMapping[IdType, typing.Any]:
    """ Return the field's cache, i.e., a mutable mapping from record id to
    a cache value.  The cache may be environment-specific.  This mapping is
    the way to retrieve a field's value for a given record.

    Calling this function multiple times, always returns the same mapping
    instance for a given environment, unless the transaction was entirely
    invalidated.
    """
    field_cache = env._field_cache_memo.get(self)
    if field_cache is None:
        env._field_cache_memo[self] = field_cache = self._get_cache_impl(env)
    return field_cache


def _get_cache_impl(self, env: Environment) -> MutableMapping[IdType, typing.Any]:
    """ Implementation of :meth:`_get_cache`.  This method may provide a
    view to the actual cache, depending on the needs of the field.
    """
    cache = env.transaction.field_data[self]
    if self in env._field_depends_context:
        cache = cache.setdefault(env.cache_key(self), {})
    return cache


def _invalidate_cache(self, env: Environment, ids: Collection[IdType] | None = None) -> None:
    """ Invalidate the field's cache for the given ids, or all record ids if ``None``. """
    cache = env.transaction.field_data.get(self)
    if not cache:
        return

    caches = cache.values() if self in env._field_depends_context else (cache,)
    for field_cache in caches:
        if ids is None:
            field_cache.clear()
            continue
        for id_ in ids:
            field_cache.pop(id_, None)


def _get_all_cache_ids(self, env: Environment) -> Collection[IdType]:
    """ Return all the record ids that have a value in cache in any environment. """
    cache = env.transaction.field_data[self]
    if self in env._field_depends_context:
        # trick to cheaply "merge" the keys of the environment-specific dicts
        return collections.ChainMap(*cache.values())
    return cache


def _cache_missing_ids(self, records: BaseModel) -> Iterator[IdType]:
    """ Generator of ids that have no value in cache. """
    field_cache = self._get_cache(records.env)
    return (id_ for id_ in records._ids if id_ not in field_cache)


def _filter_not_equal(self, records: ModelType, cache_value: typing.Any) -> ModelType:
    """ Return the subset of ``records`` for which the value of ``self`` is
    either not in cache, or different from ``cache_value``.
    """
    field_cache = self._get_cache(records.env)
    ids_to_update = tuple(
        record_id
        for record_id in records._ids
        if field_cache.get(record_id, SENTINEL) != cache_value
    )
    return records.__class__(records.env, ids_to_update, records._prefetch_ids)


def _to_prefetch(self, record: ModelType) -> ModelType:
    """ Return a recordset including ``record`` to prefetch the field. """
    ids = expand_ids(record.id, record._prefetch_ids)
    field_cache = self._get_cache(record.env)
    prefetch_ids = (id_ for id_ in ids if id_ not in field_cache)
    return record.browse(prefetch_ids)


def _insert_cache(self, records: BaseModel, values: Iterable) -> None:
    """ Update the cache of the given records with the corresponding values,
    ignoring the records that don't have a value in cache already.  This
    enables to keep the pending updates of records, and flush them later.
    """
    field_cache = self._get_cache(records.env)
    # call setdefault for all ids, values (looping in C)
    # this is ~15% faster than the equivalent:
    # ```
    # for record, value in zip(records._ids, values):
    #   field_cache.setdefault(record, value)
    # ```
    collections.deque(map(field_cache.setdefault, records._ids, values), maxlen=0)


def _update_cache(self, records: BaseModel, cache_value: typing.Any, dirty: bool = False) -> None:
    """ Update the value in the cache for the given records, and optionally
    make the field dirty for those records (for stored column fields only).

    One can normally make a clean field dirty but not the other way around.
    Updating a dirty field without ``dirty=True`` is a programming error and
    logs an error.

    :param dirty: whether ``field`` must be made dirty on ``record`` after
        the update
    """
    env = records.env
    field_cache = self._get_cache(env)
    for id_ in records._ids:
        field_cache[id_] = cache_value

    # dirty only makes sense for stored column fields
    if self.column_type and self.store:
        if dirty:
            env._field_dirty[self].update(id_ for id_ in records._ids if id_)
        else:
            dirty_ids = env._field_dirty.get(self)
            if dirty_ids and not dirty_ids.isdisjoint(records._ids):
                _logger.error(
                    "Field._update_cache() updating the value on %s.%s where dirty flag is already set",
                    records, self.name, stack_info=True,
                )
