"""Conversions of the values of a field between the database, the cache, the records and the clients."""

from __future__ import annotations

import typing
from psycopg2.extras import Json as PsycopgJson

if typing.TYPE_CHECKING:
    pass


def convert_to_column(self, value, record, values=None, validate=True):
    """ Convert ``value`` from the ``write`` format to the SQL parameter
    format for SQL conditions. This is used to compare a field's value when
    the field actually stores multiple values (translated or company-dependent).
    """
    if value is None or value is False:
        return None
    if isinstance(value, str):
        return value
    elif isinstance(value, bytes):
        return value.decode()
    else:
        return str(value)


def convert_to_column_insert(self, value, record, values=None, validate=True):
    """ Convert ``value`` from the ``write`` format to the SQL parameter
    format for INSERT queries. This method handles the case of fields that
    store multiple values (translated or company-dependent).
    """
    value = self.convert_to_column(value, record, values, validate)
    if not self.company_dependent:
        return value
    fallback = record.env['ir.default']._get_model_defaults(record._name).get(self.name)
    if value == self.convert_to_column(fallback, record):
        return None
    return PsycopgJson({record.env.company.id: value})


def convert_to_cache(self, value, records, validate=True):
    """ Convert ``value`` to the cache format; ``value`` may come from an
    assignment, or have the format of methods :meth:`BaseModel.read` or
    :meth:`BaseModel.write`. If the value represents a recordset, it should
    be added for prefetching on ``record``.

    :param value:
    :param record:
    :param bool validate: when True, field-specific validation of ``value``
        will be performed
    """
    return value


def convert_to_record(self, value, record):
    """ Convert ``value`` from the cache format to the record format.
    If the value represents a recordset, it should share the prefetching of
    ``record``.
    """
    return False if value is None else value


def convert_to_read(self, value, record, use_display_name=True):
    """ Convert ``value`` from the record format to the format returned by
    method :meth:`BaseModel.read`.

    :param value:
    :param record:
    :param bool use_display_name: when True, the value's display name will be
        computed using `display_name`, if relevant for the field
    """
    return False if value is None else value


def convert_to_write(self, value, record):
    """ Convert ``value`` from any format to the format of method
    :meth:`BaseModel.write`.
    """
    cache_value = self.convert_to_cache(value, record, validate=False)
    record_value = self.convert_to_record(cache_value, record)
    return self.convert_to_read(record_value, record)


def convert_to_export(self, value, record):
    """ Convert ``value`` from the record format to the export format. """
    if not value:
        return ''
    return value


def convert_to_display_name(self, value, record):
    """ Convert ``value`` from the record format to a suitable display name. """
    return str(value) if value else False
