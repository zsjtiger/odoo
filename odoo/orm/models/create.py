# Part of Odoo. See LICENSE file for full copyright and licensing details.
"""Create: the creation of records, the default values and the loading of records."""

from __future__ import annotations

import logging
import re
import typing
from collections import defaultdict
from collections.abc import Iterable

import psycopg2.errors
import psycopg2.extensions

from odoo.exceptions import ValidationError, UserError
from odoo.tools import (
    clean_context, OrderedSet,
    split_every,
    SQL,
)
from odoo.tools.text.translate import _


from odoo.orm.core.commands import Command
from odoo.orm.fields import Field
from odoo.orm.models import LOG_ACCESS_COLUMNS


if typing.TYPE_CHECKING:
    from collections.abc import Sequence
    from typing import Self
    from odoo.orm.core.types import ValuesType


_logger = logging.getLogger('odoo.models')

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


def create(self, vals_list: list[ValuesType]) -> Self:
    assert isinstance(vals_list, (list, tuple))
    if not vals_list:
        return self.browse()

    self = self.browse()
    self.check_access('create')

    # check access to all user-provided fields
    field_names = OrderedSet(fname for vals in vals_list for fname in vals)
    field_names.update(
        field_name
        for context_key in self.env.context
        if context_key.startswith('default_')
        and (field_name := context_key[8:])
        and field_name in self._fields
    )
    for field_name in field_names:
        field = self._fields.get(field_name)
        if field is None:
            raise ValueError(f"Invalid field {field_name!r} in {self._name!r}")
        self.check_field_access(field, 'write')

    new_vals_list = self._prepare_create_values(vals_list)

    # classify fields for each record
    data_list = []
    determine_inverses = defaultdict(OrderedSet)       # {inverse: fields}

    for vals in new_vals_list:
        precomputed = vals.pop('__precomputed__', ())

        # distribute fields into sets for various purposes
        data = {}
        data['stored'] = stored = {}
        data['inversed'] = inversed = {}
        data['cached_only'] = cached_only = {}
        data['inherited'] = inherited = defaultdict(dict)
        data['protected'] = protected = set()
        for key, val in vals.items():
            field = self._fields.get(key)
            if not field:
                raise ValueError("Invalid field %r on model %r" % (key, self._name))
            if field.store:
                stored[key] = val
            if field.inherited:
                inherited[field.related_field.model_name][key] = val
            elif field.inverse and field not in precomputed:
                inversed[key] = val
                determine_inverses[field.inverse].add(field)
            elif not field.store and not field.compute:
                # cache only fields with `field.inverse` will be handed by `inversed` correctly
                cached_only[key] = val
            # protect editable computed fields and precomputed fields
            # against (re)computation
            if (field.compute and (not field.readonly or field.precompute)) or key in cached_only:
                protected.update(self.pool.field_computed.get(field, [field]))
            if field.type == 'many2one' and field.bypass_search_access and not self.env.su:
                self.env[field.comodel_name].browse(field.convert_to_cache(val, self)).check_access('read')

        data_list.append(data)

    # create or update parent records
    for model_name, parent_name in self._inherits.items():
        parent_data_list = []
        for data in data_list:
            if not data['stored'].get(parent_name):
                parent_data_list.append(data)
            elif data['inherited'][model_name]:
                parent = self.env[model_name].browse(data['stored'][parent_name])
                parent.write(data['inherited'][model_name])

        if parent_data_list:
            parents = self.env[model_name].create([
                data['inherited'][model_name]
                for data in parent_data_list
            ])
            for parent, data in zip(parents, parent_data_list):
                data['stored'][parent_name] = parent.id

    # create records with stored fields
    records = self._create(data_list)

    # protect fields being written against recomputation
    protected_fields = [(data['protected'], data['record']) for data in data_list]
    with self.env.protecting(protected_fields):
        # fill cached_only fields
        for data in data_list:
            if vals := data['cached_only']:
                data['record']._update_cache(vals)
        # call inverse method for each group of fields
        for fields in sorted(determine_inverses.values(), key=lambda fields: min(self._fields_update_order__[f] for f in fields)):
            # determine which records to inverse for those fields
            inv_names = {field.name for field in fields}
            inv_rec_ids = []
            for data in data_list:
                if inv_names.isdisjoint(data['inversed']):
                    continue
                record = data['record']
                record._update_cache({
                    fname: value
                    for fname, value in data['inversed'].items()
                    if fname in inv_names and fname not in data['stored']
                })
                inv_rec_ids.append(record.id)

            inv_records = self.browse(inv_rec_ids)
            next(iter(fields)).determine_inverse(inv_records)
            # Values of non-stored fields were cached before running inverse methods. In case of x2many create
            # commands, the cache may therefore hold NewId records. We must now invalidate those values.
            inv_relational_fnames = [field.name for field in fields if field.type in ('one2many', 'many2many') and not field.store]
            inv_records.invalidate_recordset(fnames=inv_relational_fnames)

    # invalidate the cache
    if cache_name := self._clear_cache_name:
        self.env.transaction.invalidate_ormcache(cache_name)

    # check Python constraints for non-stored inversed fields
    for data in data_list:
        data['record']._validate_fields(data['inversed'], data['stored'])

    if self._check_company_auto:
        records._check_company()

    import_module = self.env.context.get('_import_current_module')
    if not import_module: # not an import -> bail
        return records

    # It is to support setting xids directly in create by
    # providing an "id" key (otherwise stripped by create) during an import
    # (which should strip 'id' from the input data anyway)
    noupdate = self.env.context.get('noupdate', False)

    xids = (v.get('id') for v in vals_list)
    self.env['ir.model.data']._update_xmlids([
        {
            'xml_id': xid if '.' in xid else ('%s.%s' % (import_module, xid)),
            'record': rec,
            # note: this is not used when updating o2ms above...
            'noupdate': noupdate,
        }
        for rec, xid in zip(records, xids)
        if xid and isinstance(xid, str)
    ])

    return records


def _create(self, data_list: list[ValuesType]) -> Self:
    assert data_list
    assert not self._abstract, f"Cannot create records for abstract model {self._name}"
    cr = self.env.cr
    self.env.transaction._wrote__ = True

    # insert rows in batches of maximum INSERT_BATCH_SIZE
    ids: list[int] = []                     # ids of created records
    other_fields: OrderedSet[Field] = OrderedSet()  # non-column fields

    for data_sublist in split_every(INSERT_BATCH_SIZE, data_list):
        stored_list = [data['stored'] for data in data_sublist]
        fnames = sorted({name for stored in stored_list for name in stored})

        columns: list[str] = []
        rows: list[list[typing.Any]] = [[] for _ in stored_list]
        for fname in fnames:
            field = self._fields[fname]
            if field.column_type:
                columns.append(fname)
                for stored, row in zip(stored_list, rows):
                    if fname in stored:
                        row.append(field.convert_to_column_insert(stored[fname], self, stored))
                    else:
                        row.append(SQL_DEFAULT)
            else:
                other_fields.add(field)

            if field.type == 'properties':
                # force calling fields.create for properties field because
                # we might want to update the parent definition
                other_fields.add(field)

        if not columns:
            # manage the case where we create empty records
            columns = ['id']
            for row in rows:
                row.append(SQL_DEFAULT)

        cr.execute(SQL(
            'INSERT INTO %s (%s) VALUES %s RETURNING "id"',
            SQL.identifier(self._table),
            SQL(', ').join(map(SQL.identifier, columns)),
            SQL(', ').join(tuple(row) for row in rows),
        ))
        ids.extend(id_ for id_, in cr.fetchall())

    # put the new records in cache, and update inverse fields, for many2one
    records = self.browse(ids)
    inverses_update = defaultdict(list)     # {(field, value): ids}
    common_set_vals = set(LOG_ACCESS_COLUMNS + ['id', 'parent_path'])
    for data, record in zip(data_list, records):
        data['record'] = record
        # DLE P104: test_inherit.py, test_50_search_one2many
        vals = dict({k: v for d in data['inherited'].values() for k, v in d.items()}, **data['stored'])
        set_vals = common_set_vals.union(vals)

        # put None in cache for all fields that are not part of the INSERT
        for field in self._fields.values():
            if not field.store:
                continue
            if field.type in ('one2many', 'many2many'):
                field._update_cache(record, ())
            elif field.name not in set_vals:
                field._update_cache(record, None)

        for fname, value in vals.items():
            field = self._fields[fname]
            if field.type not in ('one2many', 'many2many', 'html'):
                cache_value = field.convert_to_cache(value, record)
                field._update_cache(record, cache_value)
                if field.type in ('many2one', 'many2one_reference') and self.pool.field_inverses[field]:
                    inverses_update[(field, cache_value)].append(record.id)

    for (field, value), record_ids in inverses_update.items():
        field._update_inverses(self.browse(record_ids), value)

    # update parent_path
    records._parent_store_create()

    # protect fields being written against recomputation
    protected = [(data['protected'], data['record']) for data in data_list]
    with self.env.protecting(protected):
        # mark computed fields as todo
        records.modified(self._fields, create=True)

        if other_fields:
            # discard default values from context for other fields
            others = records.with_context(clean_context(self.env.context))
            for field in sorted(other_fields, key=lambda field: self._fields_update_order__[field]):
                field.create([
                    (other, data['stored'][field.name])
                    for other, data in zip(others, data_list)
                    if field.name in data['stored']
                ])

            # mark fields to recompute
            records.modified([field.name for field in other_fields], create=True)

    # check Python constraints for stored fields
    records._validate_fields(name for data in data_list for name in data['stored'])
    records.check_access('create')
    return records


def _load_records(self, data_list, update=False):
    original_self = self.browse()

    imd = self.env['ir.model.data'].sudo()

    # The algorithm below partitions 'data_list' into three sets: the ones
    # to create, the ones to update, and the others. For each set, we assign
    # data['record'] for each data. All those records are then retrieved for
    # the result.

    # determine existing xml_ids
    xml_ids = [data['xml_id'] for data in data_list if data.get('xml_id')]
    existing = {
        ("%s.%s" % row[1:3]): row
        for row in imd._lookup_xmlids(xml_ids, self)
    }

    # determine which records to create and update
    to_create = []                  # list of data
    to_update = []                  # list of data
    imd_data_list = []              # list of data for _update_xmlids()

    for data in data_list:
        xml_id = data.get('xml_id')
        if not xml_id:
            vals = data['values']
            if vals.get('id'):
                data['record'] = self.browse(vals['id'])
                to_update.append(data)
            elif not update:
                to_create.append(data)
            else:
                raise ValidationError(_("Cannot update a record without specifying its id or xml_id"))
            continue
        row = existing.get(xml_id)
        if not row:
            to_create.append(data)
            continue
        d_id, d_module, d_name, d_model, d_res_id, d_noupdate, r_id = row
        if self._name != d_model:
            raise ValidationError(  # pylint: disable=missing-gettext
                f"For external id {xml_id} "
                f"when trying to create/update a record of model {self._name} "
                f"found record of different model {d_model} ({d_id})"
            )
        record = self.browse(d_res_id)
        if r_id:
            data['record'] = record
            imd_data_list.append(data)
            if not (update and d_noupdate):
                to_update.append(data)
        else:
            imd.browse(d_id).unlink()
            to_create.append(data)

    # update existing records
    for data in to_update:
        data['record']._load_records_write(data['values'])

    # check for records to create with an XMLID from another module
    module = self.env.context.get('install_module')
    if module:
        prefix = module + "."
        for data in to_create:
            if data.get('xml_id') and not data['xml_id'].startswith(prefix) and not self.env.context.get('foreign_record_to_create'):
                _logger.warning("Creating record %s in module %s.", data['xml_id'], module)

    if self.env.context.get('import_file'):
        existing_modules = self.env['ir.module.module'].sudo().search([]).mapped('name')
        for data in to_create:
            xml_id = data.get('xml_id')
            if xml_id and not data.get('noupdate'):
                module_name, sep, record_id = xml_id.partition('.')
                if sep and module_name in existing_modules:
                    raise UserError(
                        _("The record %(xml_id)s has the module prefix %(module_name)s. This is the part before the '.' in the external id. Because the prefix refers to an existing module, the record would be deleted when the module is upgraded. Use either no prefix and no dot or a prefix that isn't an existing module. For example, __import__, resulting in the external id __import__.%(record_id)s.",
                          xml_id=xml_id, module_name=module_name, record_id=record_id))

    # create records
    if to_create:
        records = self._load_records_create([data['values'] for data in to_create])
        for data, record in zip(to_create, records):
            data['record'] = record
            if data.get('xml_id'):
                # add XML ids for parent records that have just been created
                for parent_model, parent_field in self._inherits.items():
                    if not data['values'].get(parent_field):
                        imd_data_list.append({
                            'xml_id': f"{data['xml_id']}_{parent_model.replace('.', '_')}",
                            'record': record[parent_field],
                            'noupdate': data.get('noupdate', False),
                        })
                imd_data_list.append(data)

    # create or update XMLIDs
    imd._update_xmlids(imd_data_list, update)

    return original_self + self.browse().concat(data['record'] for data in data_list)


def _load_records_write(self, values):
    self.ensure_one()
    to_write = {}  # Deferred the write to avoid using the old definition if it changed
    for fname in list(values):
        if fname not in self._fields or self._fields[fname].type != 'properties':
            continue
        field_converter = self._fields[fname].convert_to_cache
        to_write[fname] = dict(self[fname]._values or {}, **field_converter(values.pop(fname), self, validate=False))

    self.write(values)
    if to_write:
        self.write(to_write)
        # Because we don't know which properties was linked to which definition,
        # we can know clean properties (note that it is not mandatory, we can wait
        # that client change the record in a Form view)
        self._clean_properties()


def default_get(self, fields: Sequence[str]) -> ValuesType:
    defaults = {}
    parent_fields = defaultdict(list)
    self = self.browse()  # noqa: PLW0642
    ir_defaults = self.env['ir.default']._get_model_defaults(self._name)

    for name in fields:
        # 1. look up context
        key = 'default_' + name
        if key in self.env.context:
            defaults[name] = self.env.context[key]
            continue

        field = self._fields.get(name)
        if not field:
            continue

        # 2. look up default for non-company_dependent fields
        if not field.company_dependent and name in ir_defaults:
            defaults[name] = ir_defaults[name]
            continue

        # 3. look up field.default
        if field.default:
            defaults[name] = field.default(self)
            continue

        # 4. look up fallback for company_dependent fields
        if field.company_dependent and name in ir_defaults:
            defaults[name] = ir_defaults[name]
            continue

        # 5. delegate to parent model
        if field.inherited and self.has_field_access(field, 'write'):
            field = field.related_field
            parent_fields[field.model_name].append(field.name)

    # convert default values to the right format
    #
    # we explicitly avoid using _convert_to_write() for x2many fields,
    # because the latter leaves values like [(Command.LINK, 2),
    # (Command.LINK, 3)], which are not supported by the web client as
    # default values; stepping through the cache allows to normalize
    # such a list to [(Command.SET, 0, [2, 3])], which is properly
    # supported by the web client
    for fname, value in defaults.items():
        if fname in self._fields:
            field = self._fields[fname]
            if (
                field.relational
                and not self.env.su
                and isinstance(value, Iterable)
            ):
                # since the value will be converted into a SET, we still
                # need to check permissions for these actions
                for cmd in value:
                    command_code = cmd[0] if isinstance(cmd, (tuple, list)) and len(cmd) >= 2 else None
                    if command_code == Command.UPDATE:
                        updated_fields = cmd[2]
                    elif field.type == 'one2many' and command_code in (Command.LINK, Command.UNLINK):
                        updated_fields = (field.inverse_name,)
                    else:
                        updated_fields = None
                    if updated_fields is not None:
                        corecord = self.env[field.comodel_name].browse(cmd[1])
                        corecord.check_access('write')
                        for fname in updated_fields:
                            corecord.check_field_access(corecord._fields[fname], 'write')
                    elif command_code == Command.DELETE:
                        self.env[field.comodel_name].browse(cmd[1]).check_access('unlink')
            value = field.convert_to_cache(value, self)
            defaults[fname] = field.convert_to_write(value, self)

    # add default values for inherited fields
    for model, names in parent_fields.items():
        defaults.update(self.env[model].default_get(names))

    return defaults


def _add_missing_default_values(self, values: ValuesType) -> ValuesType:
    avoid_models = set()
    avoid_models_stack = [self]
    while avoid_models_stack:
        for parent_mname, parent_fname in avoid_models_stack.pop()._inherits.items():
            if parent_fname in values:
                avoid_models.add(parent_mname)
            else:
                # manage the case where an ancestor parent field is set
                avoid_models_stack.append(self.env[parent_mname])

    def avoid(field):
        # check whether the field is inherited from one of avoid_models
        if avoid_models:
            while field.inherited:
                field = field.related_field
                if field.model_name in avoid_models:
                    return True
        return False

    # compute missing fields
    missing_defaults = [
        name
        for name, field in self._fields.items()
        if name not in values
        if not avoid(field)
    ]

    if missing_defaults:
        # override defaults with the provided values, never allow the other way around
        defaults = self.default_get(missing_defaults)
        for name, value in defaults.items():
            if self._fields[name].type == 'many2many' and value and isinstance(value[0], int):
                # convert a list of ids into a list of commands
                defaults[name] = [Command.set(value)]
            elif self._fields[name].type == 'one2many' and value and isinstance(value[0], dict):
                # convert a list of dicts into a list of commands
                defaults[name] = [Command.create(x) for x in value]
        defaults.update(values)

    else:
        defaults = values

    # delegate the default properties to the properties field
    for field in self._fields.values():
        if field.type == 'properties':
            defaults[field.name] = field._add_default_values(self.env, defaults)

    return defaults
