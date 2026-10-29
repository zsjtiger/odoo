"""Row helpers of the database: the increment of the fields of the rows with a lock."""

from __future__ import annotations

import typing

if typing.TYPE_CHECKING:

    pass

from .builder import SQL

def increment_fields_skiplock(records, *fields):
    """
        Increment 'friendly' the given `fields` of the current `records`.
        If record is locked, we just skip the update.
        It doesn't invalidate the cache since the update is not critical.

        :param records: recordset to update
        :param fields: integer fields to increment
        :returns: whether the specified fields were incremented on any record.
        :rtype: bool
    """
    if not records:
        return False

    for field in fields:
        assert records._fields[field].type == 'integer'

    records.invalidate_recordset(fields)
    cr = records.env.cr
    tablename = records._table
    cr.execute(SQL(
        """
        UPDATE %s
           SET %s
         WHERE id IN (SELECT id FROM %s WHERE id = ANY(%s) FOR UPDATE SKIP LOCKED)
        """,
        SQL.identifier(tablename),
        SQL(', ').join(
            SQL("%s = COALESCE(%s, 0) + 1", SQL.identifier(field), SQL.identifier(field))
            for field in fields
        ),
        SQL.identifier(tablename),
        records.ids,
    ))
    return bool(cr.rowcount)
