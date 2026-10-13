# Part of Odoo. See LICENSE file for full copyright and licensing details.
"""Recordset helpers: the environments, the copies of recordsets and the caches of the records."""

from __future__ import annotations

import re
import typing
import warnings
from collections.abc import Iterable

import psycopg2.extensions



from odoo.orm.core.identifiers import NewId
from odoo.orm.core.utils import (
    Prefetch,
)

from odoo.orm.models import BaseModel
from odoo.orm.core.utils import OriginIds
if typing.TYPE_CHECKING:
    from collections.abc import Collection, Reversible, Sequence
    from odoo.orm.models.environments import Environment
    from typing import Self
    from odoo.orm.core.types import IdType, ValuesType


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


def browse(self, ids: int | typing.Iterable[IdType]=()) -> Self:
    if not ids:
        ids = ()
    elif ids.__class__ is int:
        ids = (ids,)
    else:
        ids = tuple(ids)
        assert all(ids) or all(isinstance(x, NewId) or x for x in ids), "Invalid falsy real id"
    return self.__class__(self.env, ids, ids)


def ensure_one(self) -> Self:
    try:
        # unpack to ensure there is only one value is faster than len when true and
        # has a significant impact as this check is largely called
        _id, = self._ids
        return self
    except ValueError:
        raise ValueError("Expected singleton: %s" % self)


def sudo(self, flag: bool=True) -> Self:
    assert isinstance(flag, bool)
    if flag == self.env.su:
        return self
    return self.with_env(self.env(su=flag))


def with_user(self, user: BaseModel | IdType) -> Self:
    if not user:
        return self
    return self.with_env(self.env(user=user, su=False))


def with_company(self, company: BaseModel | IdType) -> Self:
    if not company:
        # With company = None/False/0/[]/empty recordset: keep current environment
        return self

    company_id = int(company)
    allowed_company_ids = self.env.companies.ids
    if company_id == allowed_company_ids[0]:
        return self
    if company_id in allowed_company_ids:
        allowed_company_ids.remove(company_id)
    allowed_company_ids.insert(0, company_id)

    return self.with_context(allowed_company_ids=allowed_company_ids)


def with_context(self, ctx: dict[str, typing.Any] | None=None, /, **overrides) -> Self:
    context = dict(ctx if ctx is not None else self.env.context, **overrides)
    if 'company' in context:
        warnings.warn(
            "Context key 'company' is not recommended, because "
            "of its special meaning in @depends_context.",
        )
    if 'allowed_company_ids' not in context and 'allowed_company_ids' in self.env.context:
        # Force 'allowed_company_ids' to be kept when context is overridden
        # without 'allowed_company_ids'
        context['allowed_company_ids'] = self.env.context['allowed_company_ids']
    return self.with_env(self.env(context=context))


def with_prefetch(self, prefetch_ids: Reversible[IdType] | None=None) -> Self:
    if prefetch_ids is None:
        prefetch_ids = self._ids
    return self.__class__(self.env, self._ids, prefetch_ids)


def new(self, values: ValuesType | None=None, origin: Self | None=None, ref: str | None=None) -> Self:
    assert not self._abstract, f"Cannot instantiate abstract model {self._name}"
    if values is None:
        values = {}
    if origin is not None:
        origin = origin.id
    record = self.browse((NewId(origin, ref),))
    record._update_cache(values, validate=False)

    return record


def concat(self, it: Iterable[Self]=(), /, *args: Self) -> Self:
    if args:
        warnings.warn("Since 20.0, use concat() with only one iterable")
    if self:
        warnings.warn("Since 20.0, use concat() on an empty recordset")
    ids = []
    prefetch_ids_list = []
    for arg in (self, *it, *args):
        try:
            if arg._name != self._name:
                raise TypeError(f"inconsistent models in: {self} + {arg}")
            if not arg._ids:
                continue
            ids.extend(arg._ids)
            prefetch_ids_list.append(arg._prefetch_ids)
        except AttributeError:
            raise TypeError(f"unsupported operand types in: {self} + {arg!r}")
    ids = tuple(ids)
    if len(prefetch_ids_list) == 1:
        prefetch_ids = prefetch_ids_list[0]
    else:
        prefetch_ids = Prefetch.union(ids, *prefetch_ids_list)
    return self.__class__(self.env, ids, prefetch_ids)


def union(self, it: Iterable[Self]=(), /, *args: Self) -> Self:
    if args:
        warnings.warn("Since 20.0, use union() with only one iterable")
    if self:
        warnings.warn("Since 20.0, use union() on an empty recordset")
    ids = []
    prefetch_ids_list = []
    for arg in (self, *it, *args):
        try:
            if arg._name != self._name:
                raise TypeError(f"inconsistent models in: {self} | {arg}")
            if not arg._ids:
                continue
            ids.extend(arg._ids)
            prefetch_ids_list.append(arg._prefetch_ids)
        except AttributeError:
            raise TypeError(f"unsupported operand types in: {self} | {arg!r}")
    ids = tuple(dict.fromkeys(ids))
    if len(prefetch_ids_list) == 1:
        prefetch_ids = prefetch_ids_list[0]
    else:
        prefetch_ids = Prefetch.union(ids, *prefetch_ids_list)
    return self.__class__(self.env, ids, prefetch_ids)


def _convert_to_record(self, values):
    return {
        name: self._fields[name].convert_to_record(value, self)
        for name, value in values.items()
    }


def _convert_to_write(self, values):
    fields = self._fields
    result = {}
    for name, value in values.items():
        if name in fields:
            field = fields[name]
            value = field.convert_to_write(value, self)
            if not isinstance(value, NewId):
                result[name] = value
    return result


def _update_cache(self, values: ValuesType, validate: bool=True) -> None:
    self.ensure_one()
    fields = self._fields
    try:
        field_values = [(fields[name], value) for name, value in values.items() if name != 'id']
    except KeyError as e:
        raise ValueError("Invalid field %r on model %r" % (e.args[0], self._name))

    # convert monetary fields after other columns for correct value rounding
    for field, value in sorted(field_values, key=lambda item: self._fields_update_order__[item[0]]):
        value = field.convert_to_cache(value, self, validate)
        field._update_cache(self, value)

        # set inverse fields on new records in the comodel
        if field.relational:
            inv_recs = self[field.name].filtered(lambda r: not r.id)
            if not inv_recs:
                continue
            # we need to adapt the value of the inverse fields to integrate self into it:
            # x2many fields should add self, while many2one fields should replace with self
            for invf in self.pool.field_inverses[field]:
                invf._update_inverse(inv_recs, self)


def _invalidate_cache(self, fnames: Collection[str] | None=None, ids: Sequence[IdType] | None=None) -> None:
    if ids is not None and not ids:  # Avoid invalidating field_inverses for no reason
        return

    if fnames is None:
        fields = self._fields.values()
    else:
        fields = [self._fields[fname] for fname in fnames]

    env = self.env
    for field in fields:
        field._invalidate_cache(env, ids)
        if field.type == 'one2many':
            # skip invalidation of inverse for o2m fields
            # (o2m is "computed" from m2o)
            continue
        for invf in self.pool.field_inverses[field]:
            self.env[invf.model_name].flush_model([invf.name])
            invf._invalidate_cache(env)
    self.env.transaction.invalidate_access_cache(self._name)


def with_env(self, env: Environment) -> Self:
    return self.__class__(env, self._ids, self._prefetch_ids)


def _origin(self) -> Self:
    if all(self._ids):
        return self  # already real records
    ids = tuple(OriginIds(self._ids))
    prefetch_ids = OriginIds(self._prefetch_ids)
    return self.__class__(self.env, ids, prefetch_ids)


def ids(self) -> list[int]:
    if all(self._ids):
        return list(self._ids)  # already real records
    return list(OriginIds(self._ids))


def update(self, values: ValuesType) -> None:
    for name, value in values.items():
        self[name] = value
