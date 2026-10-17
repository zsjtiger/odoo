"""Conversions of the values of the properties between the database, the cache, the records and the clients."""

from __future__ import annotations

import copy
import json
import typing
from odoo.tools import html_sanitize

if typing.TYPE_CHECKING:
    pass

from .mapping import Property

def convert_to_column(self, value, record, values=None, validate=True):
    if not value:
        return None

    value = self.convert_to_cache(value, record, validate=validate)
    return json.dumps(value)


def convert_to_cache(self, value, records, validate=True):
    # any format -> cache format {name: value} or None
    if not value:
        return None

    if isinstance(value, Property):
        value = value._values

    elif isinstance(value, dict):
        # avoid accidental side effects from shared mutable data
        value = copy.deepcopy(value)

    elif isinstance(value, str):
        value = json.loads(value)
        if not isinstance(value, dict):
            raise ValueError(f"Wrong property value {value!r}")

    elif isinstance(value, list):
        # Convert the list with all definitions into a simple dict
        # {name: value} to store the strict minimum on the child
        self._remove_display_name(value)
        value = self._list_to_dict(value)

    else:
        raise TypeError(f"Wrong property type {type(value)!r}")

    if validate:
        # Sanitize `_html` flagged properties
        for property_name, property_value in value.items():
            if property_name.endswith('_html'):
                value[property_name] = html_sanitize(
                    property_value,
                    **self.HTML_SANITIZE_OPTIONS,
                )

    return value


def convert_to_record(self, value, record):
    return Property(value or {}, self, record)


def convert_to_read(self, value, record, use_display_name=True):
    return self.convert_to_read_multi([value], record, use_display_name)[0]


def convert_to_read_multi(self, values, records, use_display_name=True):
    if not records:
        return values
    assert len(values) == len(records)

    # each value is either False or a dict
    result = []
    for record, value in zip(records, values):
        value = value._values if isinstance(value, Property) else value  # Property -> dict
        if definition := self._get_properties_definition(record):
            value = value or {}
            assert isinstance(value, dict), f"Wrong type {value!r}"
            result.append(self._dict_to_list(value, definition))
        else:
            result.append([])

    res_ids_per_model = self._get_res_ids_per_model(records.env, result)

    # value is in record format
    for value in result:
        self._parse_json_types(value, records.env, res_ids_per_model)

    if use_display_name:
        for value in result:
            self._add_display_name(value, records.env)

    return result


def convert_to_write(self, value, record):
    """If we write a list on the child, update the definition record."""
    return value


def convert_to_export(self, value, record):
    """ Convert value from the record format to the export format. """
    if isinstance(value, Property):
        value = value._values
    return value or ''
