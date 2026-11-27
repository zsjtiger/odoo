# Part of Odoo. See LICENSE file for full copyright and licensing details.
"""Database schema of the models: tables, columns and SQL constraints.

The methods of :class:`~odoo.orm.models.BaseModel` with the same names delegate
to the functions of this module.
"""
import logging

import psycopg2.errors

from odoo.tools import SQL, format_list, sql
from odoo.tools.misc import exception_to_unicode

from odoo.orm.core.utils import check_object_name

_logger = logging.getLogger('odoo.orm.models')


def get_columns_from_sql_diagnostics(cr, diagnostics, *, check_registry=False) -> list[str]:
    """Given the diagnostics of an error, return the affected column names by the constraint.
    Return an empty list if we cannot determine the columns.
    """
    if column := diagnostics.column_name:
        return [column]
    if not check_registry:
        return []
    cr.execute(SQL("""
        SELECT
            ARRAY(
                SELECT attname FROM pg_attribute
                WHERE attrelid = conrelid
                AND attnum = ANY(conkey)
            ) as "columns"
        FROM pg_constraint
        JOIN pg_class t ON t.oid = conrelid
        WHERE conname = %s
            AND t.relname = %s
            AND t.relnamespace = current_schema::regnamespace
    """, diagnostics.constraint_name, diagnostics.table_name))
    columns = cr.fetchone()
    return columns[0] if columns else []


def raise_on_invalid_object_name(name):
    if not check_object_name(name):
        msg = "The _name attribute %s is not valid." % name
        raise ValueError(msg)


def check_removed_columns(records, log=False):
    if records._abstract:
        return
    # iterate on the database columns to drop the NOT NULL constraints of
    # fields which were required but have been removed (or will be added by
    # another module)
    cr = records.env.cr
    cols = [name for name, field in records._fields.items()
                 if field.store and field.column_type]
    cr.execute(SQL(
        """ SELECT a.attname, a.attnotnull
              FROM pg_class c, pg_attribute a
             WHERE c.relname=%s
               AND c.relnamespace = current_schema::regnamespace
               AND c.oid=a.attrelid
               AND a.attisdropped=%s
               AND pg_catalog.format_type(a.atttypid, a.atttypmod) NOT IN ('cid', 'tid', 'oid', 'xid')
               AND a.attname NOT IN %s """,
        records._table, False, tuple(cols),
    ))

    for row in cr.dictfetchall():
        if log:
            _logger.debug("column %s is in the table %s but not in the corresponding object %s",
                          row['attname'], records._table, records._name)
        if row['attnotnull']:
            sql.drop_not_null(cr, records._table, row['attname'])


def auto_init(records) -> None:
    raise_on_invalid_object_name(records._name)

    # This prevents anything called by this method (in particular default
    # values) from prefetching a field for which the corresponding column
    # has not been added in database yet!
    records = records.with_context(prefetch_fields=False)

    cr = records.env.cr
    update_custom_fields = records.env.context.get('update_custom_fields', False)
    must_create_table = not sql.table_exists(cr, records._table)
    parent_path_compute = False

    if records._auto:
        if must_create_table:
            def make_type(field):
                typ = field.stored_sql_column_type
                if field.required:
                    typ = SQL("%s NOT NULL", typ)
                return typ

            sql.create_model_table(cr, records._table, records._description, [
                (field.name, make_type(field), field.string)
                for field in sorted(records._fields.values(), key=lambda f: f.column_order)
                if field.name != 'id' and field.store and field.column_type
            ])
            from odoo.modules.db import RANDOM_SERIAL  # noqa: PLC0415
            if RANDOM_SERIAL and not records._name.startswith('test'):
                # Randomize first sequence number to avoid having records
                # with similar ids when testing. For example, avoid having
                # first res_users and res_partner sharing the same id.
                # Just using the number of existing tables multiplied by a
                # prime.
                cr.execute("""
                    SELECT setval(
                        pg_get_serial_sequence(%s, 'id'),
                        abs(hashtext(%s)) %% 97 + 103)""",
                    (records._table, records._table))

        if records._parent_store:
            if not sql.column_exists(cr, records._table, 'parent_path'):
                sql.create_column(records.env.cr, records._table, 'parent_path', 'varchar')
                parent_path_compute = True
            records._check_parent_path()

        if not must_create_table:
            records._check_removed_columns(log=False)

        # update the database schema for fields
        columns = sql.table_columns(cr, records._table)

        for field in sorted(records._fields.values(), key=lambda f: f.column_order):
            if not field.store:
                continue
            if field.manual and not update_custom_fields:
                continue            # don't update custom fields
            field.update_db(records, columns)

    if records._auto:
        records._add_sql_constraints()

    if parent_path_compute:
        records._parent_store_compute()


def check_parent_path(records):
    field = records._fields.get('parent_path')
    if field is None:
        _logger.error("add a field parent_path on model %r: `parent_path = fields.Char(index=True)`.", records._name)
    elif not field.index:
        _logger.error('parent_path field on model %r should be indexed! Add index=True to the field definition.', records._name)


def add_sql_constraints(records):
    for obj in records._table_objects.values():
        obj.apply_to_database(records)


def sql_error_to_message(records, exc: psycopg2.Error) -> str:
    if (constraint_name := exc.diag.constraint_name) and (cons := records._table_objects.get(constraint_name)):
        cons_rec = records.env['ir.model.constraint'].sudo().search_fetch([
            ('name', '=', constraint_name),
            ('model.model', '=', records._name),
        ], ['message'], limit=1)
        if message := cons_rec.message:
            return message
        # get the message from the object
        if message := cons.get_error_message(records, exc.diag):
            return message
    return records._sql_error_to_message_generic(exc)


def sql_error_to_message_generic(records, exc: psycopg2.Error) -> str:
    diag = exc.diag
    unknown = records.env._('Unknown')
    model_string = records.env['ir.model']._get(records._name).name or records._description
    info = {
        'model_display': f"'{model_string}' ({records._name})",
        'table_name': diag.table_name,
        'constraint_name': diag.constraint_name,
    }
    if records._table == diag.table_name:
        columns = get_columns_from_sql_diagnostics(records.env.cr, diag, check_registry=True)
    else:
        columns = get_columns_from_sql_diagnostics(records.env.cr, diag)
        info['model_display'] = unknown
    if not columns:
        info['field_display'] = unknown
    elif len(columns) == 1 and (field := records._fields.get(columns[0])):
        field_string = field._description_string(records.env)
        info['field_display'] = f"'{field_string}' ({field.name})"
    else:
        info['field_display'] = f"'{format_list(records.env, columns)}'"

    if isinstance(exc, psycopg2.errors.NotNullViolation):
        return records.env._(
            "Missing required field %(field_display)s for model %(model_display)s",
            **info,
        )

    if isinstance(exc, psycopg2.errors.ForeignKeyViolation):
        if len(columns) != 1:
            info['field_display'] = info['constraint_name']
        return records.env._(
            "Another model is using the record you are trying to delete.\n\n"
            "The troublemaker is: %(model_display)s\n"
            "Thanks to the following constraint: %(field_display)s\n"
            "How about archiving the record instead?",
            **info,
        )

    if isinstance(exc, psycopg2.errors.UniqueViolation) and columns:
        column_names = [records._fields[f].string if f in records._fields else f for f in columns]
        info['field_display'] = f"'{', '.join(columns)}' ({format_list(records.env, column_names)})"
        info['detail'] = diag.message_detail  # contains conflicting key and value
        return records.env._("The value for %(field_display)s already exists.\n\nDetail: %(detail)s\n", **info)

    # No good message can be created for psycopg2.errors.CheckViolation

    # fallback
    return exception_to_unicode(exc)

