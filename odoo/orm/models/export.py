# Part of Odoo. See LICENSE file for full copyright and licensing details.
"""Export and load helpers: the rows and records of the export and import of data."""

from __future__ import annotations

import collections
import contextlib
import functools
import itertools
import logging
import re
import typing
from collections import defaultdict
from collections.abc import Iterable

import psycopg2.errors
import psycopg2.extensions

from odoo.exceptions import UserError
from odoo.tools import (
    unique,
    groupby,
)
from odoo.tools.translate import _, LazyTranslate




if typing.TYPE_CHECKING:
    pass


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

from odoo.orm.models import BaseModel, fix_import_export_id_paths, itemgetter_tuple


def _export_rows(self, fields, *, _is_toplevel_call=True):
    import_compatible = self.env.context.get('import_compat', True)
    lines = []


    if not _is_toplevel_call:
        # {properties_field: {property_name: [property_type, {record_id: value}]}}
        cache_properties = self.env.cr.cache['export_properties_cache']
    else:
        cache_properties = self.env.cr.cache['export_properties_cache'] = defaultdict(dict)

        def fill_properties_cache(records, fnames_by_path, fname):
            """ Fill the cache for the ``fname`` properties field and return it """
            cache_properties_field = cache_properties[records._fields[fname]]

            # read properties to have all the logic of Properties.convert_to_read_multi
            for row in records.read([fname]):
                properties = row[fname]
                if not properties:
                    continue
                rec_id = row['id']

                for property in properties:
                    current_prop_name = property['name']
                    if f"{fname}.{current_prop_name}" not in fnames_by_path:
                        continue
                    property_type = property['type']
                    if current_prop_name not in cache_properties_field:
                        cache_properties_field[current_prop_name] = [property_type, {}]

                    __, cache_by_id = cache_properties_field[current_prop_name]
                    if rec_id in cache_by_id:
                        continue

                    value = property.get('value')
                    if property_type in ('many2one', 'many2many'):
                        if not isinstance(value, list):
                            value = [value] if value else []
                        value = self.env[property['comodel']].browse([val[0] for val in value])
                    elif property_type == 'tags' and value:
                        value = ",".join(
                            next(iter(tag[1] for tag in property['tags'] if tag[0] == v), '')
                            for v in value
                        )
                    elif property_type == 'selection':
                        value = dict(property['selection']).get(value, '')
                    cache_by_id[rec_id] = value

        def fetch_fields(records, field_paths):
            """ Fill the cache of ``records`` for all ``field_paths`` recursively included properties"""
            if not records:
                return

            fnames_by_path = dict(groupby(
                [path for path in field_paths if path and path[0] not in ('id', '.id')],
                # strip the language part of translated paths ('name@fr_FR')
                lambda path: path[0].split('@')[0],
            ))

            # Fetch needed fields (remove '.property_name' part)
            fnames = list(unique(fname.split('.')[0] for fname in fnames_by_path))
            if translated_fnames := [fname for fname in fnames if records._fields[fname].translate]:
                # fetch all the languages at once instead of one query each
                records.with_context(prefetch_langs=True).fetch(translated_fnames)
            records.fetch(fnames)
            # Fill the cache of the properties field
            for fname in fnames:
                field = records._fields[fname]
                if field.type == 'properties':
                    fill_properties_cache(records, fnames_by_path, fname)

            # Call it recursively for relational field (included property relational field)
            for fname, paths in fnames_by_path.items():
                if '.' in fname:  # Properties field
                    fname, prop_name = fname.split('.')
                    field = records._fields[fname]
                    assert field.type == 'properties' and prop_name

                    property_type, property_cache = cache_properties[field].get(prop_name, ('char', None))
                    if property_type not in ('many2one', 'many2many') or not property_cache:
                        continue
                    model = next(iter(property_cache.values())).browse()
                    subrecords = model.union(property_cache[rec_id] for rec_id in records.ids if rec_id in property_cache)
                else:  # Normal field
                    field = records._fields[fname]
                    if not field.relational:
                        continue
                    subrecords = records[fname]

                paths = [path[1:] or ['display_name'] for path in paths]
                fetch_fields(subrecords, paths)

        fetch_fields(self, fields)

    for record in self:
        # main line of record, initially empty
        current = [''] * len(fields)
        lines.append(current)

        # list of primary fields followed by secondary field(s)
        primary_done = []

        # process column by column
        for i, path in enumerate(fields):
            if not path:
                continue

            name = path[0]
            if name in primary_done:
                continue

            if name == '.id':
                current[i] = str(record.id)
            elif name == 'id':
                current[i] = (record._name, record.id)
            else:
                prop_name = None
                fname, __, lang = name.partition('@')
                if '.' in fname:  # Properties field
                    fname, prop_name = fname.split('.')
                    field = record._fields[fname]
                    field_type, cache_value = cache_properties[field].get(prop_name, ('char', None))
                    value = cache_value.get(record.id, '') if cache_value else ''
                else:  # Normal field
                    field = record._fields[fname]
                    field_type = field.type
                    if field.translate:
                        # 'check_translations' skips the delayed translations,
                        # which are not reimportable next to their source
                        translated = record.with_context(check_translations=True)
                        value = (translated.with_context(lang=lang) if lang else translated)[fname]
                    else:
                        value = record[fname]

                # this part could be simpler, but it has to be done this way
                # in order to reproduce the former behavior
                if not isinstance(value, BaseModel):
                    current[i] = field.convert_to_export(value, record)

                elif import_compatible and field_type == 'reference':
                    current[i] = f"{value._name},{value.id}"

                else:
                    primary_done.append(name)
                    # recursively export the fields that follow name; use
                    # 'display_name' where no subfield is exported
                    fields2 = [(p[1:] or ['display_name'] if p and p[0] == name else [])
                               for p in fields]

                    # in import_compat mode, m2m should always be exported as
                    # a comma-separated list of xids or names in a single cell
                    if import_compatible and field_type == 'many2many':
                        index = None
                        # find out which subfield the user wants & its
                        # location as we might not get it as the first
                        # column we encounter
                        for name in ['id', 'name', 'display_name']:
                            with contextlib.suppress(ValueError):
                                index = fields2.index([name])
                                break
                        if index is None:
                            # not found anything, assume we just want the
                            # display_name in the first column
                            name = None
                            index = i

                        if name == 'id':
                            xml_ids = [xid for _, xid in value._ensure_xml_id()]
                            current[index] = ','.join(xml_ids)
                        else:
                            current[index] = ','.join(value.mapped('display_name')) if value else ''
                        continue

                    lines2 = value._export_rows(fields2, _is_toplevel_call=False)
                    if lines2:
                        # merge first line with record's main line
                        for j, val in enumerate(lines2[0]):
                            if val or isinstance(val, (int, float)):
                                current[j] = val
                        # append the other lines at the end
                        lines += lines2[1:]
                    else:
                        current[i] = ''

    # if any xid should be exported, only do so at toplevel
    if _is_toplevel_call and any(f[-1] == 'id' for f in fields):
        bymodels = collections.defaultdict(set)
        xidmap = collections.defaultdict(list)
        # collect all the tuples in "lines" (along with their coordinates)
        for i, line in enumerate(lines):
            for j, cell in enumerate(line):
                if isinstance(cell, tuple):
                    bymodels[cell[0]].add(cell[1])
                    xidmap[cell].append((i, j))
        # for each model, xid-export everything and inject in matrix
        for model, ids in bymodels.items():
            for record, xid in self.env[model].browse(ids)._ensure_xml_id():
                for i, j in xidmap.pop((record._name, record.id)):
                    lines[i][j] = xid
        assert not xidmap, "failed to export xids for %s" % ', '.join('%s:%s' % it for it in xidmap.items())

    if _is_toplevel_call:
        self.env.cr.cache.pop('export_properties_cache', None)

    return lines


def export_data(self, fields_to_export):
    if not (self.env.is_admin() or self.env.user.has_group('base.group_allow_export')):
        raise UserError(_("You don't have the rights to export data. Please contact an Administrator."))
    fields_to_export = [fix_import_export_id_paths(f) for f in fields_to_export]
    return {'datas': self._export_rows(fields_to_export)}


def _extract_records(self, field_paths, data, log=lambda a: None, limit=float('inf')):
    fields = self._fields

    get_o2m_values = itemgetter_tuple([
        index
        for index, fnames in enumerate(field_paths)
        if fnames[0] in fields and fields[fnames[0]].type == 'one2many'
    ])
    get_nono2m_values = itemgetter_tuple([
        index
        for index, fnames in enumerate(field_paths)
        if fnames[0] not in fields or fields[fnames[0]].type != 'one2many'
    ])
    # Checks if the provided row has any non-empty one2many fields
    def only_o2m_values(row):
        return any(get_o2m_values(row)) and not any(get_nono2m_values(row))

    property_definitions = {}
    property_columns = defaultdict(list)
    for fname, *__ in field_paths:
        if not fname:
            continue
        if '.' not in fname:
            if fname not in fields:
                raise ValueError(f'Invalid field name {fname!r}')
            continue

        f_prop_name, property_name = fname.split('.')
        if f_prop_name not in fields or fields[f_prop_name].type != 'properties':
            # Can be .id
            continue

        definition = self.get_property_definition(fname)
        if not definition:
            # Can happen if someone remove the property, UserError ?
            raise ValueError(f"Property {property_name!r} doesn't have any definition on {fname!r} field")

        property_definitions[fname] = definition
        property_columns[f_prop_name].append(fname)

    # m2o fields can't be on multiple lines so don't take it in account
    # for only_o2m_values rows filter, but special-case it later on to
    # be handled with relational fields (as it can have subfields).
    def is_relational(fname):
        return (
            fname in fields and
            fields[fname].relational
        ) or (
            fname in property_definitions and
            property_definitions[fname].get('type') in ('many2one', 'many2many')
        )

    index = 0
    while index < len(data) and index < limit:
        row = data[index]

        # copy non-relational fields to record dict
        record = {
            fnames[0]: value
            for fnames, value in zip(field_paths, row)
            if not is_relational(fnames[0])
        }

        # Get all following rows which have relational values attached to
        # the current record (no non-relational values)
        record_span = itertools.takewhile(
            only_o2m_values,
            (data[j] for j in range(index + 1, len(data))),
        )
        # stitch record row back on for relational fields
        record_span = list(itertools.chain([row], record_span))

        for relfield, *__ in field_paths:
            if not is_relational(relfield):
                continue

            if relfield not in property_definitions:
                comodel = self.env[fields[relfield].comodel_name]
            else:
                comodel = self.env[property_definitions[relfield]['comodel']]

            # get only cells for this sub-field, should be strictly
            # non-empty, field path [None] is for display_name field
            indices, subfields = zip(*((index, fnames[1:] or [None])
                                       for index, fnames in enumerate(field_paths)
                                       if fnames[0] == relfield))

            # return all rows which have at least one value for the
            # subfields of relfield
            relfield_data = [it for it in map(itemgetter_tuple(indices), record_span) if any(it)]
            record[relfield] = [
                subrecord
                for subrecord, _subinfo in comodel._extract_records(subfields, relfield_data, log=log)
            ]

        for properties_fname, property_indexes_names in property_columns.items():
            properties = []
            for property_name in property_indexes_names:
                value = record.pop(property_name)
                properties.append(dict(**property_definitions[property_name], value=value))
            record[properties_fname] = properties

        yield record, {'rows': {
            'from': index,
            'to': index + len(record_span) - 1,
        }}
        index += len(record_span)


def _convert_records(self, records, *, log=lambda a: None, savepoint):
    field_names = {name: field.string for name, field in self._fields.items()}
    if self.env.lang:
        field_names.update(self.env['ir.model.fields'].get_field_string(self._name))

    convert = self.env['ir.fields.converter'].for_model(self, savepoint=savepoint)

    def _log(base, record, field, exception):
        type = 'warning' if isinstance(exception, Warning) else 'error'
        # logs the logical (not human-readable) field name for automated
        # processing of response, but injects human readable in message
        field_name = field_names[field]
        exc_vals = dict(base, record=record, field=field_name)
        record = dict(base, type=type, record=record, field=field,
                      message=str(exception.args[0]) % exc_vals)
        if len(exception.args) > 1:
            info = {}
            if exception.args[1] and isinstance(exception.args[1], dict):
                info = exception.args[1]
            # ensure field_name is added to the exception. Used in import to
            # concatenate multiple errors in the same block
            info['field_name'] = field_name
            record.update(info)
        log(record)

    for stream_index, (record, extras) in enumerate(records):
        # xid
        xid = record.get('id', False)
        # dbid
        dbid = False
        if record.get('.id'):
            try:
                dbid = int(record['.id'])
            except ValueError:
                # in case of overridden id column
                dbid = record['.id']
            if not self.search([('id', '=', dbid)]):
                log(dict(extras,
                    type='error',
                    record=stream_index,
                    field='.id',
                    message=_(u"Unknown database identifier '%s'", dbid)))
                dbid = False

        converted = convert(record, functools.partial(_log, extras, stream_index))

        yield dbid, xid, converted, dict(extras, record=stream_index)


def _validate_fields(self, field_names: Iterable[str], excluded_names: Iterable[str]=()) -> None:
    methods = self._constraint_methods
    if not methods:
        return
    # run constrains just as sudoed computed-stored fields
    # see Field.compute_value()
    records = self.sudo()
    field_names = set(field_names)
    excluded_names = set(excluded_names)
    for check in methods:
        if (not field_names.isdisjoint(check._constrains)
                and excluded_names.isdisjoint(check._constrains)):
            check(records)
