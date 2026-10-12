# Part of Odoo. See LICENSE file for full copyright and licensing details.
"""Write and create helpers: the values to write and the precomputed values of new records."""

from __future__ import annotations

import json
import logging
import re
import typing
from collections import defaultdict

import psycopg2.errors
import psycopg2.extensions

from odoo.exceptions import AccessError, UserError
from odoo.tools import split_every, SQL
from odoo.tools.constants import IN_MAX
from odoo.tools.translate import _

from odoo.orm.core.utils import SUPERUSER_ID
from odoo.orm.fields import Field, determine

if typing.TYPE_CHECKING:
    from odoo.orm.core.types import ValuesType


_unlink = logging.getLogger('odoo.models.unlink')

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

from odoo.orm.models import LOG_ACCESS_COLUMNS


def _prepare_create_values(self, vals_list: list[ValuesType]) -> list[ValuesType]:
    bad_names = ['id', 'parent_path']
    if self._log_access:
        # the superuser can set log_access fields while loading registry
        if not (self.env.uid == SUPERUSER_ID and not self.pool.ready):
            bad_names.extend(LOG_ACCESS_COLUMNS)

    # also discard precomputed readonly fields (to force their computation)
    bad_names.extend(
        fname
        for fname, field in self._fields.items()
        if field.precompute and field.readonly
    )

    result_vals_list = []
    for vals in vals_list:
        # add default values
        vals = self._add_missing_default_values(vals)

        # add magic fields
        for fname in bad_names:
            vals.pop(fname, None)
        if self._log_access:
            vals.setdefault('create_uid', self.env.uid)
            vals.setdefault('create_date', self.env.cr.now())
            vals.setdefault('write_uid', self.env.uid)
            vals.setdefault('write_date', self.env.cr.now())

        result_vals_list.append(vals)

    # add precomputed fields
    self._add_precomputed_values(result_vals_list)

    return result_vals_list


def _add_precomputed_values(self, vals_list: list[ValuesType]) -> None:
    precomputable = {
        fname: field
        for fname, field in self._fields.items()
        if field.precompute
    }
    if not precomputable:
        return

    # when several fields have the same compute, setting any of them should
    # not compute the others (and leave them to False)
    for vals in vals_list:
        given_fnames = [fname for fname in vals if fname in precomputable]
        for fname in given_fnames:
            for field in self.pool.field_computed[self._fields[fname]]:
                vals.setdefault(field.name, False)

    # determine which vals must be completed
    vals_list_todo = [
        vals
        for vals in vals_list
        if any(fname not in vals for fname in precomputable)
    ]
    if not vals_list_todo:
        return

    # create new records for the vals that must be completed
    records = self.browse().concat(self.new(vals) for vals in vals_list_todo)

    for record, vals in zip(records, vals_list_todo):
        vals['__precomputed__'] = precomputed = set()
        for fname, field in precomputable.items():
            if fname not in vals:
                # computed stored fields with a column
                # have to be computed before create
                # s.t. required and constraints can be applied on those fields.
                field_value = record.sudo()[fname] if field.compute_sudo else record[fname]
                vals[fname] = field.convert_to_write(field_value, self)
                precomputed.add(field)


def _compute_field_value(self, field: Field) -> None:
    determine(field.compute, self)

    if field.store and any(self._ids):
        # check constraints of the fields that have been computed
        fnames = [f.name for f in self.pool.field_computed[field]]
        self.filtered('id')._validate_fields(fnames)


def _write_multi(self, vals_list: list[ValuesType]) -> None:
    assert len(self) == len(vals_list)

    if not self:
        return
    self.env.transaction._wrote__ = True

    # determine records that require updating parent_path
    parent_records = self._parent_store_update_prepare(vals_list)

    if self._log_access:
        # set magic fields (already done by write(), but not for computed fields)
        log_vals = {'write_uid': self.env.uid, 'write_date': self.env.cr.now()}
        vals_list = [(log_vals | vals) for vals in vals_list]

    # determine SQL updates, grouped by set of updated fields:
    # {(col1, col2, col3): [(id, val1, val2, val3)]}
    updates = defaultdict(list)
    for record, vals in zip(self, vals_list):
        # sort vals.items() by key, then retrieve its keys and values
        fnames, row = zip(*sorted(vals.items()))
        updates[fnames].append(record._ids + row)

    # perform updates (fnames, rows) in batches
    updates_list = [
        (fnames, sub_rows)
        for fnames, rows in updates.items()
        for sub_rows in split_every(UPDATE_BATCH_SIZE, rows)
    ]

    # update columns by group of updated fields
    for fnames, rows in updates_list:
        columns = []
        assignments = []
        for fname in fnames:
            field = self._fields[fname]
            assert field.store and field.column_type
            column = SQL.identifier(fname)
            # the type cast is necessary for some values, like NULLs
            expr = SQL('"__tmp".%s::%s', column, SQL.identifier(field.column_type[0]))
            if field.translate is True:
                # this is the SQL equivalent of:
                # None if expr is None else (
                #     (column or {'en_US': next(iter(expr.values()))}) | expr
                # )
                expr = SQL(
                    """CASE
                        WHEN (%(expr)s -> 0)::boolean THEN
                            COALESCE(
                                %(table)s.%(column)s,
                                jsonb_build_object('en_US', jsonb_path_query_first(%(expr)s -> 1, '$.*'))
                            ) || (%(expr)s -> 1)
                        ELSE (%(expr)s -> 1)
                    END""",
                    table=SQL.identifier(self._table),
                    column=column,
                    expr=expr,
                )
            if field.company_dependent:
                fallbacks = self.env['ir.default']._get_field_column_fallbacks(self._name, fname)
                expr = SQL(
                    """(SELECT jsonb_object_agg(d.key, d.value)
                    FROM jsonb_each(COALESCE(%(table)s.%(column)s, '{}'::jsonb) || %(expr)s) d
                    JOIN jsonb_each(%(fallbacks)s) f
                    ON d.key = f.key AND d.value != f.value)""",
                    table=SQL.identifier(self._table),
                    column=column,
                    expr=expr,
                    fallbacks=fallbacks
                )
            columns.append(column)
            assignments.append(SQL("%s = %s", column, expr))

        self.env.execute_query(SQL(
            """ UPDATE %(table)s
                SET %(assignments)s
                FROM (VALUES %(values)s) AS "__tmp"("id", %(columns)s)
                WHERE %(table)s."id" = "__tmp"."id"
            """,
            table=SQL.identifier(self._table),
            assignments=SQL(", ").join(assignments),
            values=SQL(", ").join(rows),
            columns=SQL(", ").join(columns),
        ))

    # update parent_path
    if parent_records:
        parent_records._parent_store_update()


def write(self, vals: ValuesType) -> typing.Literal[True]:
    if not self:
        return True

    self.check_access('write')
    for field_name in vals:
        try:
            self.check_field_access(self._fields[field_name], 'write')
        except KeyError as e:
            raise ValueError(f"Invalid field {field_name!r} in {self._name!r}") from e
    env = self.env

    bad_names = {'id', 'parent_path'}
    if self._log_access:
        # the superuser can set log_access fields while loading registry
        if not (self.env.uid == SUPERUSER_ID and not self.pool.ready):
            bad_names.update(LOG_ACCESS_COLUMNS)

    # set magic fields
    vals = {key: val for key, val in vals.items() if key not in bad_names}
    if self._log_access:
        vals.setdefault('write_uid', self.env.uid)
        vals.setdefault('write_date', self.env.cr.now())

    field_values = sorted(
        [(self._fields[key], val) for key, val in vals.items()],
        key=lambda item: self._fields_update_order__[item[0]]
    )                                           # [(field, value)]
    determine_inverses = defaultdict(list)      # {inverse: fields}
    fnames_modifying_relations = []
    protected = set()
    for field, value in field_values:
        if field.inverse:
            if field.type in ('one2many', 'many2many'):
                # The written value is a list of commands that must applied
                # on the field's current value. Because the field is
                # protected while being written, the field's current value
                # will not be computed and default to an empty recordset. So
                # make sure the field's value is in cache before writing, in
                # order to avoid an inconsistent update.
                self[field.name]
            determine_inverses[field.inverse].append(field)
        if self.pool.is_modifying_relations(field):
            fnames_modifying_relations.append(field.name)
        if field.inverse or (field.compute and not field.readonly):
            if field.store or field.type not in ('one2many', 'many2many'):
                # Protect the field from being recomputed while being
                # inversed. In the case of non-stored x2many fields, the
                # field's value may contain unexpeced new records (created
                # by command 0). Those new records are necessary for
                # inversing the field, but should no longer appear if the
                # field is recomputed afterwards. Not protecting the field
                # will automatically invalidate the field from the cache,
                # forcing its value to be recomputed once dependencies are
                # up-to-date.
                protected.update(self.pool.field_computed.get(field, [field]))

    # force the computation of fields that are computed with some assigned
    # fields, but are not assigned themselves
    to_compute = [field.name
                  for field in protected
                  if field.compute and field.name not in vals]
    if to_compute:
        self._recompute_recordset(to_compute)

    # protect fields being written against recomputation
    with env.protecting(protected, self):
        # Determine records depending on values. When modifying a relational
        # field, you have to recompute what depends on the field's values
        # before and after modification.  This is because the modification
        # has an impact on the "data path" between a computed field and its
        # dependency.  Note that this double call to modified() is only
        # necessary for relational fields.
        #
        # It is best explained with a simple example: consider two sales
        # orders SO1 and SO2.  The computed total amount on sales orders
        # indirectly depends on the many2one field 'order_id' linking lines
        # to their sales order.  Now consider the following code:
        #
        #   line = so1.line_ids[0]      # pick a line from SO1
        #   line.order_id = so2         # move the line to SO2
        #
        # In this situation, the total amount must be recomputed on *both*
        # sales order: the line's order before the modification, and the
        # line's order after the modification.
        self.modified(fnames_modifying_relations, before=True)

        real_recs = self.filtered('id')

        for field, value in field_values:
            field.write(self, value)

        # determine records depending on new values
        #
        # Call modified after write, because the modified can trigger a
        # search which can trigger a flush which can trigger a recompute
        # which remove the field from the recompute list while all the
        # values required for the computation could not be yet in cache.
        # e.g. Write on `name` of `res.partner` trigger the recompute of
        # `display_name`, which triggers a search on child_ids to find the
        # childs to which the display_name must be recomputed, which
        # triggers the flush of `display_name` because the _order of
        # res.partner includes display_name. The computation of display_name
        # is then done too soon because the parent_id was not yet written.
        # (`test_01_website_reset_password_tour`)
        self.modified(vals)

        if self._parent_store and self._parent_name in vals:
            self.flush_model([self._parent_name])

        # validate non-inversed fields first
        inverse_fields = [f.name for fs in determine_inverses.values() for f in fs]
        real_recs._validate_fields(vals, inverse_fields)

        for fields in determine_inverses.values():
            # write again on non-stored fields that have been invalidated from cache
            for field in fields:
                if not field.store and (not field.inherited or field.type not in ('one2many', 'many2many')) and any(field._cache_missing_ids(real_recs)):
                    field.write(real_recs, vals[field.name])

            # inverse records that are not being computed
            try:
                fields[0].determine_inverse(real_recs)
            except AccessError as e:
                if fields[0].inherited:
                    description = self.env['ir.model']._get(self._name).name
                    raise AccessError(_(
                        "%(previous_message)s\n\nImplicitly accessed through '%(document_kind)s' (%(document_model)s).",
                        previous_message=e.args[0],
                        document_kind=description,
                        document_model=self._name,
                    ))
                raise

        # invalidate the cache
        if real_recs and (cache_name := self._clear_cache_name) and (
            self._clear_cache_on_fields is None
            or not vals.keys().isdisjoint(self._clear_cache_on_fields)
        ):
            self.env.transaction.invalidate_ormcache(cache_name)

        # validate inversed fields
        real_recs._validate_fields(inverse_fields)

    if self._check_company_auto:
        self._check_company(list(vals))
    return True


def unlink(self) -> typing.Literal[True]:
    if not self:
        return True

    self.check_access('unlink')
    self.env.transaction._wrote__ = True

    for func in self._ondelete_methods:
        # func._ondelete is True => should be called during uninstallation
        # func._ondelete is False => should be called unless its module is being uninstalled
        if (
            func._ondelete
            or not self.pool.uninstalling_modules
            or func.__module__.split('.')[2] not in self.pool.uninstalling_modules
        ):
            func(self)

    # TOFIX: this avoids an infinite loop when trying to recompute a
    # field, which triggers the recomputation of another field using the
    # same compute function, which then triggers again the computation
    # of those two fields
    for field in self._fields.values():
        self.env.remove_to_compute(field, self)

    self.env.flush_all()

    cr = self.env.cr
    Data = self.env['ir.model.data'].sudo().with_context({})
    Defaults = self.env['ir.default'].sudo()
    Attachment = self.env['ir.attachment'].sudo()
    ir_model_data_unlink = Data
    ir_attachment_unlink = Attachment

    # mark fields that depend on 'self' to recompute them after 'self' has
    # been deleted (like updating a sum of lines after deleting one line)
    with self.env.protecting(self._fields.values(), self):
        self.modified(self._fields, before=True)

    for sub_ids in split_every(IN_MAX, self.ids):
        records = self.browse(sub_ids)

        cr.execute(SQL(
            "DELETE FROM %s WHERE id IN %s",
            SQL.identifier(self._table), sub_ids,
        ))

        # Removing the ir_model_data reference if the record being deleted
        # is a record created by xml/csv file, as these are not connected
        # with real database foreign keys, and would be dangling references.
        #
        # Note: the following steps are performed as superuser to avoid
        # access rights restrictions, and with no context to avoid possible
        # side-effects during admin calls.
        data = Data.search([('model', '=', self._name), ('res_id', 'in', sub_ids)])
        ir_model_data_unlink |= data

        # For the same reason, remove the relevant records in ir_attachment
        # (the search is performed with sql as the search method of
        # ir_attachment is overridden to hide attachments of deleted
        # records)
        cr.execute(SQL(
            "SELECT id FROM ir_attachment WHERE res_model=%s AND res_id IN %s",
            self._name, sub_ids,
        ))
        ir_attachment_unlink |= Attachment.browse(row[0] for row in cr.fetchall())

        # don't allow fallback value in ir.default for many2one company dependent fields to be deleted
        # Exception: when 'force_delete', these fallbacks can be deleted by Defaults.discard_records(records)
        if (many2one_fields := self.env.registry.many2one_company_dependents[self._name]) and not self.env.context.get('force_delete'):
            IrModelFields = self.env["ir.model.fields"]
            field_ids = tuple(IrModelFields._get_ids(field.model_name).get(field.name) for field in many2one_fields)
            sub_ids_json_text = tuple(json.dumps(id_) for id_ in sub_ids)
            if default := Defaults.search([('field_id', 'in', field_ids), ('json_value', 'in', sub_ids_json_text)], limit=1, order='id desc'):
                ir_field = default.field_id.sudo()
                field = self.env[ir_field.model]._fields[ir_field.name]
                record = self.browse(json.loads(default.json_value))
                raise UserError(_('Unable to delete %(record)s because it is used as the default value of %(field)s', record=record, field=field))

        # on delete set null/restrict for jsonb company dependent many2one
        for field in many2one_fields:
            model = self.env[field.model_name]
            if field.ondelete == 'restrict' and not self.env.context.get('force_delete'):
                if res := self.env.execute_query(SQL(
                    """
                    SELECT id, %(field)s
                    FROM %(table)s
                    WHERE %(field)s IS NOT NULL
                    AND %(field)s @? %(jsonpath)s
                    ORDER BY id
                    LIMIT 1
                    """,
                    table=SQL.identifier(model._table),
                    field=SQL.identifier(field.name),
                    jsonpath=f"$.* ? ({' || '.join(f'@ == {id_}' for id_ in sub_ids)})",
                )):
                    on_restrict_id, field_json = res[0]
                    to_delete_id = next(iter(id_ for id_ in field_json.values()))
                    on_restrict_record = model.browse(on_restrict_id)
                    to_delete_record = self.browse(to_delete_id)
                    raise UserError(_('You cannot delete %(to_delete_record)s, as it is used by %(on_restrict_record)s',
                                      to_delete_record=to_delete_record, on_restrict_record=on_restrict_record))
            else:
                self.env.execute_query(SQL(
                    """
                    UPDATE %(table)s
                    SET %(field)s = (
                        SELECT jsonb_object_agg(
                            key,
                            CASE
                                WHEN value::int4 in %(ids)s THEN NULL
                                ELSE value::int4
                            END)
                        FROM jsonb_each_text(%(field)s)
                    )
                    WHERE %(field)s IS NOT NULL
                    AND %(field)s @? %(jsonpath)s
                    """,
                    table=SQL.identifier(model._table),
                    field=SQL.identifier(field.name),
                    ids=sub_ids,
                    jsonpath=f"$.* ? ({' || '.join(f'@ == {id_}' for id_ in sub_ids)})",
                ))

        # For the same reason, remove the defaults having some of the
        # records as value
        Defaults.discard_records(records)

    # invalidate the *whole* cache, since the orm does not handle all
    # changes made in the database, like cascading delete!
    self.env.invalidate_all(flush=False)
    if ir_model_data_unlink:
        ir_model_data_unlink.unlink()
    if ir_attachment_unlink:
        ir_attachment_unlink.unlink()
    if cache_name := self._clear_cache_name:
        self.env.transaction.invalidate_ormcache(cache_name)

    # auditing: deletions are infrequent and leave no trace in the database
    _unlink.info('User #%s deleted %s records with IDs: %r', self.env.uid, self._name, self.ids)

    return True
