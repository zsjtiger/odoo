"""The base of the x2many fields: the cache, the commands and the conversions of the values of the relation."""

from __future__ import annotations

import copy
import itertools
import typing
from odoo.tools import SQL, OrderedSet, unique
from odoo.tools.misc import SENTINEL
from odoo.orm.core.commands import Command
from odoo.orm.core.domains import Domain
from odoo.orm.core.identifiers import NewId
from odoo.orm.models import BaseModel
from odoo.orm.database.query import Query, TableSQL
from odoo.orm.core.utils import Prefetch

if typing.TYPE_CHECKING:
    from odoo.orm.core.types import CommandValue

    OnDelete = typing.Literal['cascade', 'set null', 'restrict']

from .base import _Relational


class _RelationalMulti(_Relational):
    r"Abstract class for relational fields \*2many."
    # X2many fields must be written last, because they flush other fields when deleting lines.
    write_sequence = 20

    # Important: the cache contains the ids of all the records in the relation,
    # including inactive records.  Inactive records are filtered out by
    # convert_to_record(), depending on the context.

    def _update_inverse(self, records, value):
        new_id = value.id
        assert not new_id, "Field._update_inverse can only be called with a new id"
        field_cache = self._get_cache(records.env)
        for record_id in records._ids:
            assert not record_id, "Field._update_inverse can only be called with new records"
            cache_value = field_cache.get(record_id, SENTINEL)
            if cache_value is SENTINEL:
                records.env.transaction.field_data_patches[self][record_id].append(new_id)
            else:
                field_cache[record_id] = tuple(unique(cache_value + (new_id,)))

    def _update_cache(self, records, cache_value, dirty=False):
        field_patches = records.env.transaction.field_data_patches.get(self)
        if field_patches and records:
            for record in records:
                ids = field_patches.pop(record.id, ())
                if ids:
                    value = tuple(unique(itertools.chain(cache_value, ids)))
                else:
                    value = cache_value
                super()._update_cache(record, value, dirty)
            return
        super()._update_cache(records, cache_value, dirty)

    def _compute_related(self, records):
        # Related fields for x2m must be computed in sudo to ensure cache
        # consistency with the related field which is fetched in sudo.
        return super()._compute_related(records.sudo())

    def convert_to_cache(self, value, records, validate=True):
        if isinstance(value, tuple):  # (1, 2, 3)
            if records and not any(records._ids):
                return tuple(it and NewId(it) for it in value)
            return value

        elif isinstance(value, BaseModel):  # recordset
            if validate and value._name != self.comodel_name:
                raise ValueError("Wrong value for %s: %s" % (self, value))
            ids = value._ids
            if records and not any(records._ids):
                # x2many field value of new record is new records
                ids = tuple(it and NewId(it) for it in ids)
            return ids

        elif value is False or value is None:
            return ()

        elif isinstance(value, list) and value and not isinstance(value[0], (tuple, list)):  # [1,2,3]
            if records and not any(records._ids):
                return tuple(it and NewId(it) for it in value)
            return tuple(value)

        elif isinstance(value, list):
            if len(records) > 1:
                raise ValueError("Wrong value for %s with %d records: %r" % (self, len(records), value))
            # [(COMMAND.LINK, 100, 0), ...], []
            record = records
            # value is a list/tuple of commands, dicts or record ids
            comodel = record.env[self.comodel_name]
            # if record is new, the field's value is new records
            if record and not record.id:
                browse = lambda it: comodel.browse((it and NewId(it),))
            else:
                browse = comodel.browse
            # determine the value ids: in case of a real record or a new record
            # with origin, take its current value
            ids = OrderedSet(record[self.name]._ids if record._origin else ())
            # modify ids with the commands
            for command in value:
                if isinstance(command, (tuple, list)):
                    if command[0] == Command.CREATE:
                        ids.add(comodel.new(command[2], ref=command[1]).id)
                    elif command[0] == Command.UPDATE:
                        line = browse(command[1])
                        # don't update real records, otherwise some subsequent
                        # write() won't do the actual update
                        if not line.id:
                            line._update_cache(command[2], validate)
                        ids.add(line.id)
                    elif command[0] in (Command.DELETE, Command.UNLINK):
                        ids.discard(browse(command[1]).id)
                    elif command[0] == Command.LINK:
                        ids.add(browse(command[1]).id)
                    elif command[0] == Command.CLEAR:
                        ids.clear()
                    elif command[0] == Command.SET:
                        ids = OrderedSet(browse(it).id for it in command[2])
                elif isinstance(command, dict):
                    ids.add(comodel.new(command).id)
                else:
                    ids.add(browse(command).id)
            # return result as a tuple
            return tuple(ids)

        raise ValueError("Wrong value for %s: %s" % (self, value))

    def convert_to_record(self, value, record: BaseModel):
        # use registry to avoid creating a recordset for the model
        prefetch_ids = Prefetch.relational(self, record)
        env = record.env
        Comodel = env.registry[self.comodel_name]
        corecords = Comodel(env, value, prefetch_ids)
        if not env.su and corecords and not self.bypass_search_access:
            # For performance, this slightly modified version of
            # `_filtered_access` does not recheck permissions for records marked
            # as inaccessible. Without this, we would recheck record access on
            # each `convert_to_record` call if one of them in inaccessible.
            read_access = env._access_cache[Comodel._name]
            if all(map(read_access.get, corecords._ids)):
                pass  # all records are accessible
            elif all(map(read_access.__contains__, corecords._origin)):
                # we have a value for all origins in access
                # consider inaccessible records as inaccessible
                if not corecords.browse().has_access('read'):
                    return corecords.browse()
                if corecords._origin:
                    def accessible(rec):
                        origin = rec._origin
                        # no origin: new id without origin
                        return not origin or read_access[origin.id]
                    corecords = corecords.filtered(accessible)
            else:
                # default behaviour
                corecords = corecords._filtered_access('read')
        if (
            Comodel._active_name
            and self.context.get('active_test', env.context.get('active_test', True))
        ):
            corecords = corecords.filtered(Comodel._active_name).with_prefetch(prefetch_ids)
        return corecords

    def convert_to_record_multi(self, values, records: BaseModel):
        # return the list of ids as a recordset without duplicates
        # same logic as convert_to_record (but references multiple source records)
        ids = tuple(unique(id_ for ids in values for id_ in ids))
        return self.convert_to_record(ids, records)

    def convert_to_read(self, value, record, use_display_name=True):
        return value.ids

    def convert_to_write(self, value, record):
        if isinstance(value, tuple):
            # a tuple of ids, this is the cache format
            value = record.env[self.comodel_name].browse(value)

        if isinstance(value, BaseModel) and value._name == self.comodel_name:
            def get_origin(val):
                return val._origin if isinstance(val, BaseModel) else val

            # make result with new and existing records
            inv_names = {field.name for field in record.pool.field_inverses[self]}
            result = [Command.set([])]
            for record in value:
                origin = record._origin
                if not origin:
                    values = record._convert_to_write({
                        name: record[name]
                        for name in record._cache
                        if name not in inv_names
                    })
                    result.append(Command.create(values))
                else:
                    result[0][2].append(origin.id)
                    if record != origin:
                        values = record._convert_to_write({
                            name: record[name]
                            for name in record._cache
                            if name not in inv_names and get_origin(record[name]) != origin[name]
                        })
                        if values:
                            result.append(Command.update(origin.id, values))
            return result

        if value is False or value is None:
            return [Command.clear()]

        if isinstance(value, list):
            return value

        raise ValueError("Wrong value for %s: %s" % (self, value))

    def convert_to_export(self, value, record):
        return ','.join(value.mapped('display_name')) if value else ''

    def convert_to_display_name(self, value, record):
        raise NotImplementedError()

    def get_depends(self, model):
        depends, depends_context = super().get_depends(model)
        if not self.compute and isinstance(domain := self.domain, (list, Domain)):
            domain = Domain(domain)
            depends = unique(itertools.chain(depends, (
                self.name + '.' + condition.field_expr
                for condition in domain.iter_conditions()
            )))
        return depends, depends_context

    def create(self, record_values: list[tuple[BaseModel, typing.Any]]) -> None:
        """ Write the value of ``self`` on the given records, which have just
        been created.

        :param record_values: a list of pairs ``(record, value)``, where
            ``value`` is in the format of method :meth:`BaseModel.write`
        """
        self.write_batch(record_values, create=True)

    def write(self, records: BaseModel, value):
        # discard recomputation of self on records
        records.env.remove_to_compute(self, records)
        self.write_batch([(records, value)])

    def write_batch(self, records_commands_list: list[tuple[BaseModel, typing.Any]], create: bool = False) -> None:
        raise NotImplementedError

    def _parse_write_commands(self, records_commands_list: list[tuple[BaseModel, typing.Any]]) -> tuple[BaseModel, list[tuple[BaseModel, CommandValue]]]:
        """Mutate the command list to make sure we only have command values."""
        if not records_commands_list:
            return None, records_commands_list  # not typed correctly, but falsy so we skip it
        for idx, (recs, value) in enumerate(records_commands_list):
            if isinstance(value, tuple):
                value = [Command.set(value)]
            elif isinstance(value, BaseModel) and value._name == self.comodel_name:
                value = [Command.set(value._ids)]
            elif value is False or value is None:
                value = [Command.clear()]
            elif isinstance(value, list) and value and not isinstance(value[0], (tuple, list)):
                value = [Command.set(tuple(value))]
            if not isinstance(value, list):
                raise ValueError("Wrong value for %s: %s" % (self, value))
            records_commands_list[idx] = (recs, value)
        if len(records_commands_list) == 1:
            records = records_commands_list[0][0]
        else:
            model = records_commands_list[0][0].browse()
            records = model.browse(unique(rid for recs, _cs in records_commands_list for rid in recs._ids))
        assert all(records._ids) or not any(records._ids), f"{records_commands_list} contains a mix of real and new records. It is not supported."
        return records, records_commands_list

    def _check_sudo_commands(self, comodel):
        # if the model doesn't accept sudo commands
        if not comodel._allow_sudo_commands:
            # Then, disable sudo and reset the transaction origin user
            return comodel.sudo(False).with_user(comodel.env.transaction.default_env.uid)
        return comodel

    def to_sql(self, table):
        # not allowed, since using it changes the cardinality of the query
        raise ValueError(f"Cannot generate SQL for multi-relational field {self}")

    def condition_to_sql(self, table: TableSQL, field_expr: str, operator: str, value) -> SQL:
        assert field_expr == self.name, "Supporting condition only to field"
        model = table._model
        comodel = table._model.env[self.comodel_name].with_context(**self.context)
        if not self.store:
            raise ValueError(f"Cannot convert {self} to SQL because it is not stored")

        assert operator in ('any', 'not any', 'any!', 'not any!'), \
            f"Relational field {self} expects 'any' operator"
        exists = operator in ('any', 'any!')

        field_domain = self.get_comodel_domain(model)
        if isinstance(value, Domain):
            domain = value & field_domain
            bypass_access = self.bypass_search_access or operator in ('any!', 'not any!')
            if (
                domain.is_condition('id', operator='any!', value=Query)
                and model._search is BaseModel._search
                and not (model._active_name and model.env.context.get('active_test', True))
            ):
                # ('id', 'any!', Query), so we can just use the query
                query = domain.value
            else:
                registry = model.env.registry
                for inverse_field in registry.field_inverses[self]:
                    # if the inverse is a column, already make sure it's set
                    # this is usually the case for one2many
                    if inverse_field.column_type and inverse_field not in comodel.env.registry.not_null_fields:
                        domain &= Domain(inverse_field.name, '!=', False)
                query = comodel._search(domain, bypass_access=bypass_access)
            assert isinstance(query, Query)
        elif isinstance(value, Query):
            domain = field_domain.optimize_full(comodel)
            if not domain.is_true():
                value = copy.copy(value)
                value.add_where(domain._to_sql(value.table._with_model(comodel)))
            query = value
        elif isinstance(value, SQL):
            query = comodel._search(field_domain & Domain('id', 'any!', value), active_test=False, bypass_access=True)
        else:
            assert False, f"Unimplemented condition on {self} for {type(value)}"

        if query.is_empty():
            return Domain(not exists)._to_sql(table)
        return self._condition_to_sql_relational(table, exists, query)

    def _condition_to_sql_relational(self, table: TableSQL, exists: bool, coquery: Query) -> SQL:
        raise NotImplementedError
