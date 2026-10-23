"""The helpers of the models of the registry: the xml ids, the queries on the tables, the upserts and the computed fields."""

from __future__ import annotations

import re
from collections.abc import Mapping
from psycopg2.extras import Json
from odoo import api
from odoo.tools import BinaryBytes, split_every, SQL
from odoo.tools.constants import IN_MAX
from odoo.tools.safe_eval import safe_eval, datetime, dateutil, time
from odoo.tools.text.translate import LazyTranslate


_lt = LazyTranslate(__name__)


ACCESS_ERROR_HEADER = {
    'read': _lt("You are not allowed to access '%(document_kind)s' (%(document_model)s) records."),
    'write': _lt("You are not allowed to modify '%(document_kind)s' (%(document_model)s) records."),
    'create': _lt("You are not allowed to create '%(document_kind)s' (%(document_model)s) records."),
    'unlink': _lt("You are not allowed to delete '%(document_kind)s' (%(document_model)s) records."),
}


ACCESS_ERROR_GROUPS = _lt("This operation is allowed for the following groups:\n%(groups_list)s")


ACCESS_ERROR_NOGROUP = _lt("No group currently allows this operation.")


ACCESS_ERROR_RESOLUTION = _lt("Contact your administrator to request access if necessary.")


MODULE_UNINSTALL_FLAG = 'force_delete'


RE_ORDER_FIELDS = re.compile(r'"?(\w+)"?\s*(?:asc|desc)?', flags=re.I)


SAFE_EVAL_BASE = {
    'BinaryBytes': BinaryBytes,
    'datetime': datetime,
    'dateutil': dateutil,
    'time': time,
}


def make_compute(text, deps):
    """ Return a compute function from its code body and dependencies. """
    def func(self):
        return safe_eval(text, SAFE_EVAL_BASE | {'self': self}, mode="exec")
    deps = [arg.strip() for arg in deps.split(",")] if deps else []
    return api.depends(*deps)(func)


def mark_modified(records, fnames):
    """ Mark the given fields as modified on records. """
    # protect all modified fields, to avoid them being recomputed
    fields = [records._fields[fname] for fname in fnames]
    with records.env.protecting(fields, records):
        records.modified(fnames)


def model_xmlid(module, model_name):
    """ Return the XML id of the given model. """
    return '%s.model_%s' % (module, model_name.replace('.', '_'))


def field_xmlid(module, model_name, field_name):
    """ Return the XML id of the given field. """
    return '%s.field_%s__%s' % (module, model_name.replace('.', '_'), field_name)


def selection_xmlid(module, model_name, field_name, value):
    """ Return the XML id of the given selection. """
    xmodel = model_name.replace('.', '_')
    xvalue = value.replace('.', '_').replace(' ', '_').lower()
    return '%s.selection__%s__%s__%s' % (module, xmodel, field_name, xvalue)


def query_insert(cr, table, rows):
    """ Insert rows in a table. ``rows`` is a list of dicts, all with the same
        set of keys. Return the ids of the new rows.
    """
    if isinstance(rows, Mapping):
        rows = [rows]
    cols = list(rows[0])
    ids = []
    for srows in split_every(IN_MAX, rows, list):
        query = SQL(
            "INSERT INTO %s (%s) VALUES %s RETURNING id",
            SQL.identifier(table),
            SQL(",").join(map(SQL.identifier, cols)),
            SQL(",").join(
                tuple(row.get(col) for col in cols)
                for row in srows
            ),
        )
        cr.execute(query)
        ids.extend(row[0] for row in cr.fetchall())
    return ids


def query_update(cr, table, values, selectors):
    """ Update the table with the given values (dict), and use the columns in
        ``selectors`` to select the rows to update.
    """
    query = SQL(
        "UPDATE %s SET %s WHERE %s RETURNING id",
        SQL.identifier(table),
        SQL(",").join(
            SQL("%s = %s", SQL.identifier(key), val)
            for key, val in values.items()
            if key not in selectors
        ),
        SQL(" AND ").join(
            SQL("%s = %s", SQL.identifier(key), values[key])
            for key in selectors
        ),
    )
    cr.execute(query)
    return [row[0] for row in cr.fetchall()]


def select_en(model, fnames, model_names):
    """ Select the given columns from the given model's table, with the given WHERE clause.
    Translated fields are returned in 'en_US'.
    """
    if not model_names:
        return []
    cols = SQL(", ").join(
        SQL("%s->>'en_US'", SQL.identifier(fname)) if model._fields[fname].translate else SQL.identifier(fname)
        for fname in fnames
    )
    query = SQL(
        "SELECT %s FROM %s WHERE model IN %s",
        cols,
        SQL.identifier(model._table),
        tuple(model_names),
    )
    return model.env.execute_query(query)


def upsert_en(model, fnames, rows, conflict):
    """ Insert or update the table with the given rows.

    :param model: recordset of the model to query
    :param fnames: list of column names
    :param rows: list of tuples, where each tuple value corresponds to a column name
    :param conflict: list of column names to put into the ON CONFLICT clause
    :return: the ids of the inserted or updated rows
    """
    # for translated fields, we can actually erase the json value, as
    # translations will be reloaded after this
    def identity(val):
        return val

    def jsonify(val):
        return Json({'en_US': val}) if val is not None else val

    wrappers = [(jsonify if model._fields[fname].translate else identity) for fname in fnames]
    values = [
        tuple(func(val) for func, val in zip(wrappers, row))
        for row in rows
    ]
    comma = SQL(", ").join
    query = SQL("""
        INSERT INTO %(table)s (%(cols)s) VALUES %(values)s
        ON CONFLICT (%(conflict)s) DO UPDATE SET (%(cols)s) = (%(excluded)s)
        RETURNING id
        """,
        table=SQL.identifier(model._table),
        cols=comma(SQL.identifier(fname) for fname in fnames),
        values=comma(values),
        conflict=comma(SQL.identifier(fname) for fname in conflict),
        excluded=comma(
            (
                SQL(
                    """CASE
                        WHEN %(old)s ->> 'en_US' IS DISTINCT FROM %(new)s ->> 'en_US'
                            -- the source text changed: existing translations were
                            -- made for a source that no longer exists, drop them so
                            -- they get reloaded fresh instead of being kept as if
                            -- they still applied to the current source
                            THEN %(new)s
                        ELSE COALESCE(%(old)s, '{}'::jsonb) || %(new)s
                       END""",
                    old=SQL.identifier(model._table, fname),
                    new=SQL("EXCLUDED.%s", SQL.identifier(fname)),
                )
                if model._fields[fname].translate is True
                else SQL("EXCLUDED.%s", SQL.identifier(fname))
            )
            for fname in fnames
        ),
    )
    return [id_ for id_, in model.env.execute_query(query)]
