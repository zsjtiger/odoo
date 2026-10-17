"""Database schema of the fields: the column type and the creation and update of the columns."""

from __future__ import annotations

import logging
import typing
from psycopg2.extras import Json as PsycopgJson
from odoo.tools import SQL, sql
from odoo.tools.misc import SENTINEL
from odoo.orm.database.query import Query

if typing.TYPE_CHECKING:
    from odoo.orm.core.types import BaseModel

from .base import determine

_logger = logging.getLogger('odoo.fields')


def column_type(self) -> tuple[str, str] | None:
    """ Return the actual column type for this field, if stored as a column. """
    return ('jsonb', 'jsonb') if self.company_dependent or self.translate else self._column_type


def stored_sql_column_type(self) -> SQL:
    """ Column type as stored in the database column. """
    _ident, spec = self.column_type
    return SQL(spec)  # pylint: disable=sql-injection


def sql_column_type(self) -> SQL:
    """ Column type used for casting into the field's type. """
    ident, _spec = self._column_type
    return SQL.identifier(ident)


def get_column_update(self, record: BaseModel):
    """ Return the value of record in cache as an SQL parameter formatted
    for UPDATE queries.
    """
    field_cache = record.env.transaction.field_data[self]
    record_id = record.id
    if self.company_dependent:
        values = {}
        for ctx_key, cache in field_cache.items():
            if (value := cache.get(record_id, SENTINEL)) is not SENTINEL:
                values[ctx_key[0]] = self.convert_to_column(value, record)
        return PsycopgJson(values) if values else None
    if self in record.env._field_depends_context:
        # field that will be written to the database depends on context;
        # find the first value that is set
        # If we have more than one value, it is a logical error in the
        # design of the model. In that case, we pick one at random because
        # a stored field can have only one value.
        for ctx_key, cache in field_cache.items():
            if (value := cache.get(record_id, SENTINEL)) is not SENTINEL:
                break
        else:
            raise AssertionError(f"Value not in cache for field {self} and id={record_id}")
    else:
        value = field_cache[record_id]
    return self.convert_to_column_insert(value, record, validate=False)


def column_order(self) -> int:
    """ Prescribed column order in table. """
    return 0 if self.column_type is None else sql.SQL_ORDER_BY_TYPE[self.column_type[0]]


def update_db(self, model: BaseModel, columns: dict[str, dict[str, typing.Any]]) -> None:
    """ Update the database schema to implement this field.

        :param model: an instance of the field's model
        :param columns: a dict mapping column names to their configuration in database
    """
    assert self.column_type, f"override missing of update_db for {self.type}"

    column = columns.get(self.name)

    # create/update the column, initialize it and not null constraint.
    # The index will be managed by registry.check_indexes().
    self.update_db_column(model, column)

    # initialization of values and null handling
    has_notnull = column and column['is_nullable'] == 'NO'

    if not column or (self.required and not has_notnull):
        # either we have a new column or it becomes required
        self._init_column_data(model)

    if self.required and not has_notnull:
        # _init_column_data may delay computations in post-init phase
        @model.pool.post_init
        def add_not_null():
            # At the time this function is called, the model's _fields may have been reset, although
            # the model's class is still the same. Retrieve the field to see whether the NOT NULL
            # constraint still applies.
            field = model._fields[self.name]
            if not field.required or not field.store:
                return
            if field.compute:
                query = Query(model.sudo())
                query.add_where(SQL("%s IS NULL", query.table[field.name]))
                records = model.browse(id_ for id_, in model.env.execute_query(query.select()))
                model.env.add_to_compute(field, records)
            # Flush values before adding NOT NULL constraint.
            model.flush_model([field.name])
            model.pool.post_constraint(
                model.env.cr,
                lambda cr: sql.set_not_null(cr, model._table, field.name),
                key=f"add_not_null:{model._table}:{field.name}",
            )

    elif not self.required and has_notnull:
        sql.drop_not_null(model.env.cr, model._table, self.name)


def update_db_column(self, model: BaseModel, column: dict[str, typing.Any]):
    """ Create/update the column corresponding to ``self``.

        :param model: an instance of the field's model
        :param column: the column's configuration (dict) if it exists, or ``None``
    """
    if not column:
        # the column does not exist, create it
        sql.create_column(model.env.cr, model._table, self.name, self.stored_sql_column_type, self.string)
        return
    if column['udt_name'] == self.column_type[0]:
        return
    self._convert_db_column(model, column)


def _convert_db_column(self, model: BaseModel, column: dict[str, typing.Any]):
    """ Convert the given database column to the type of the field. """
    sql.convert_column(model.env.cr, model._table, self.name, self.stored_sql_column_type)


def _init_column_data(self, model: BaseModel) -> None:
    """ Initialize null values in the column. """
    assert self.column_type and model._name == self.model_name
    # skip the initialization when there is nothing to initialize: this
    # method only fills in NULL values, and does nothing without
    # init_storage, default or compute; skip empty tables as well
    if not (self.init_storage or self.default or self.compute):
        return
    if not model.env.execute_query(SQL('SELECT 1 FROM %s LIMIT 1', SQL.identifier(model._table))):
        return
    # Check if we have a custom init function
    if self.init_storage:
        _logger.debug("Table '%s': call %s for column %s", model._table, self.init_storage, self.name)
        to_compute = determine(self.init_storage, model)
    else:
        to_compute = 'default'
    # Get the default value; ideally, we should use default_get(), but it
    # fails due to ir.default not being ready
    if self.default:
        value = self.default(model)
        if value is not None and to_compute == 'default':  # we have a default, do not recompute fields
            to_compute = False
        value = self.convert_to_write(value, model)
        value = self.convert_to_column_insert(value, model)
    else:
        value = None
    # Write value if non-NULL, except for booleans for which False means
    # the same as NULL - this saves us an expensive query on large tables,
    # if the boolean is required we still write False to allow NOT NULL constraints.
    cr = model.env.cr
    if value is False and self.type == 'boolean' and not self.required:
        value = None
    if value is not None:
        _logger.debug("Table '%s': setting default value of new column %s to %r",
                      model._table, self.name, value)
        cr.execute(SQL(
            "UPDATE %(table)s SET %(field)s = %(value)s WHERE %(field)s IS NULL",
            table=SQL.identifier(model._table),
            field=SQL.identifier(self.name),
            value=value,
        ))
    # Mark computed fields to recompute
    if to_compute and self.compute:
        cr.execute(SQL('SELECT id FROM %s WHERE %s IS NULL', SQL.identifier(model._table), SQL.identifier(self.name)))
        records = model.browse(row[0] for row in cr.fetchall())
        self._init_column_notify_compute(records)
        model.env.add_to_compute(self, records)


def _init_column_notify_compute(self, records):
    _logger.info("Prepare computation of %s in %s records", self, len(records))
    if len(records) > 100000:
        _logger.warning("%s: %s records will be computed", self, len(records))
