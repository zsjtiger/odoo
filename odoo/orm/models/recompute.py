# Part of Odoo. See LICENSE file for full copyright and licensing details.
"""Cache and recomputation: the modified fields, the triggers, the flush and the invalidation."""

from __future__ import annotations

import logging
import re
import typing
from collections.abc import Iterable

import psycopg2.errors
import psycopg2.extensions

from odoo.exceptions import MissingError
from odoo.tools import (
    OrderedSet,
    split_every,
)
from odoo.tools.translate import LazyTranslate


from odoo.orm.fields import Field

from odoo.orm.core.identifiers import NewId

if typing.TYPE_CHECKING:
    from collections.abc import Collection, Sequence
    from odoo.orm.models.registry import TriggerTree
    from odoo.orm.core.types import IdType


_lt = LazyTranslate('base')
_logger = logging.getLogger('odoo.models')
_unlink = logging.getLogger('odoo.models.unlink')

regex_order = re.compile(r'''
    ^
    (\s*
        (?P<term>((?P<field>[a-z0-9_]+)(\.(?P<property>[a-z0-9_]+))?(:(?P<func>[a-z_]+))?))
        (\s+(?P<direction>desc|asc))?
        (\s+(?P<nulls>nulls\ first|nulls\ last))?
        \s*
        (,|$)
    )+
    (?<!,)
    $
''', re.IGNORECASE | re.VERBOSE)
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

from odoo.orm.models import BaseModel


def _modified(self, fields: list[Field], create: bool) -> Iterable[tuple[Field, BaseModel, bool]]:

    # The fields' trigger trees are merged in order to evaluate all triggers
    # at once. For non-stored computed fields, `_modified_triggers` might
    # traverse the tree (at the cost of extra queries) only to know which
    # records to invalidate in cache. But in many cases, most of these
    # fields have no data in cache, so they can be ignored from the start.
    # This allows us to discard subtrees from the merged tree when they
    # only contain such fields.
    def select(field):
        return (field.compute and field.store) or bool(field._get_all_cache_ids(self.env))

    tree = self.pool.get_trigger_tree(fields, select=select)
    if not tree:
        return ()

    return self.sudo().with_context(active_test=False)._modified_triggers(tree, create)


def _modified_triggers(self, tree: TriggerTree, create: bool=False) -> Iterable[tuple[Field, BaseModel, bool]]:
    if not self:
        return

    # first yield what to compute
    for field in tree.root:
        yield field, self, create

    # then traverse dependencies backwards, and proceed recursively
    for field, subtree in tree.items():
        if create and field.type in ('many2one', 'many2one_reference'):
            # upon creation, no other record has a reference to self
            continue

        inverses = self.pool.field_inverses[field]
        if create and field.type == 'many2many' and field.store and not inverses:
            # upon creation, no other record has a reference to self
            # for this M2M because no inverse has been able to use commands.
            continue

        # subtree is another tree of dependencies
        model = self.env[field.model_name]
        for invf in inverses:
            # use an inverse of field without domain
            if not (invf.type in ('one2many', 'many2many') and invf.domain):
                if invf.type == 'many2one_reference':
                    rec_ids = OrderedSet()
                    for rec in self:
                        try:
                            if rec[invf.model_field] == field.model_name and (rec_id := rec[invf.name]):
                                rec_ids.add(rec_id)
                        except MissingError:
                            continue
                    records = model.browse(rec_ids)
                else:
                    try:
                        records = self[invf.name]
                    except MissingError:
                        records = self.exists()[invf.name]

                # TODO: find a better fix
                if field.model_name == records._name:
                    if not any(self._ids):
                        # if self are new, records should be new as well
                        records = records.browse(it and NewId(it) for it in records._ids)
                    break
        else:
            new_records = self.filtered(lambda r: not r.id)
            real_records = self - new_records
            records = model.browse()
            if real_records:
                records = model.search([(field.name, 'in', real_records.ids)], order='id')
            if new_records:
                field_cache = field._get_cache(model.env)
                cache_records = model.browse(field_cache)
                new_ids = set(self._ids)
                records |= cache_records.filtered(lambda r: not set(r[field.name]._ids).isdisjoint(new_ids))

        yield from records._modified_triggers(subtree)


def _recompute_model(self, fnames: Collection[str] | None=None) -> None:
    if fnames is None:
        fields = self._fields.values()
    else:
        fields = [self._fields[fname] for fname in fnames]

    for field in fields:
        if field.compute and field.store:
            self._recompute_field(field)


def _recompute_recordset(self, fnames: Collection[str] | None=None) -> None:
    if fnames is None:
        fields = self._fields.values()
    else:
        fields = [self._fields[fname] for fname in fnames]

    for field in fields:
        if field.compute and field.store:
            self._recompute_field(field, self._ids)


def _recompute_field(self, field: Field, ids: Sequence[IdType] | None=None) -> None:
    ids_to_compute = self.env.transaction.tocompute.get(field, ())
    if ids is None:
        ids = ids_to_compute
    else:
        ids = [id_ for id_ in ids if id_ in ids_to_compute]
    if not ids:
        return

    # do not force recomputation on new records; those will be
    # recomputed by accessing the field on the records
    records = self.browse(tuple(id_ for id_ in ids if id_))
    field.recompute(records)


def _flush(self) -> None:
    dirty_fields = self.env._field_dirty
    dirty_field_ids = {
        field: ids
        for field in self._fields.values()
        if (ids := dirty_fields.pop(field, None))
    }
    if not dirty_field_ids:
        return

    # for context-dependent fields, `get_column_update` contains the
    # logic to find which value to flush
    model = self

    # sort dirty record ids so that records with the same set of modified
    # fields are grouped together; for that purpose, map each dirty id to
    # an integer that represents its subset of dirty fields (bitmask)
    dirty_ids = sorted(
        OrderedSet(id_ for ids in dirty_field_ids.values() for id_ in ids),
        key=lambda id_: sum(
            1 << field_index
            for field_index, ids in enumerate(dirty_field_ids.values())
            if id_ in ids
        ),
    )

    # perform updates in batches in order to limit memory footprint
    BATCH_SIZE = 1000
    for some_ids in split_every(BATCH_SIZE, dirty_ids):
        vals_list = []
        try:
            for id_ in some_ids:
                record = model.browse((id_,))
                vals_list.append({
                    f.name: f.get_column_update(record)
                    for f, ids in dirty_field_ids.items()
                    if id_ in ids
                })
        except KeyError:
            raise AssertionError(
                f"Could not find all values of {record} to flush them\n"
                f"    Context: {self.env.context}\n"
                f"    Cache: {dict(record._cache)!r}"
            )
        model.browse(some_ids)._write_multi(vals_list)


def flush_model(self, fnames: Collection[str] | None=None) -> None:
    self._recompute_model(fnames)
    dirty_fields = self.env._field_dirty
    if fnames is None or any(self._fields[fname] in dirty_fields for fname in fnames):
        self._flush()


def flush_recordset(self, fnames: Collection[str] | None=None) -> None:
    if not self:
        return
    self._recompute_recordset(fnames)
    if fnames is None:
        fields = self._fields.values()
    else:
        fields = [self._fields[fname] for fname in fnames]
    ids = set(self._ids)
    dirty_fields = self.env._field_dirty
    if not all(ids.isdisjoint(dirty_fields.get(field, ())) for field in fields):
        self._flush()


def invalidate_model(self, fnames: Collection[str] | None=None, flush: bool=True) -> None:
    if flush:
        self.flush_model(fnames)
    self._invalidate_cache(fnames)


def invalidate_recordset(self, fnames: Collection[str] | None=None, flush: bool=True) -> None:
    if flush:
        self.flush_recordset(fnames)
    self._invalidate_cache(fnames, self._ids)
