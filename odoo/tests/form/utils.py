"""Helpers of the form tests: the modifiers, the dotted dictionaries and the conversion of the read values."""

from __future__ import annotations

import ast
from datetime import datetime, date
from odoo import fields

from .values import M2MValue, O2MValue

MODIFIER_ALIASES = {'1': 'True', '0': 'False'}


def convert_read_to_form(values, model_fields):
    result = {}
    for fname, value in values.items():
        field_info = {'type': 'id'} if fname == 'id' else model_fields[fname]
        if field_info['type'] == 'one2many':
            if 'edition_view' in field_info:
                subfields = field_info['edition_view']['fields']
                value = O2MValue(convert_read_to_form(vals, subfields) for vals in (value or ()))
            else:
                value = O2MValue({'id': id_} for id_ in (value or ()))
        elif field_info['type'] == 'many2many':
            value = M2MValue({'id': id_} for id_ in (value or ()))
        elif field_info['type'] == 'datetime' and isinstance(value, datetime):
            value = fields.Datetime.to_string(value)
        elif field_info['type'] == 'date' and isinstance(value, date):
            value = fields.Date.to_string(value)
        result[fname] = value
    return result


def _cleanup_from_default(type_, value):
    if not value:
        if type_ == 'one2many':
            return O2MValue()
        elif type_ == 'many2many':
            return M2MValue()
        elif type_ in ('integer', 'float'):
            return 0
        return value

    if type_ == 'one2many':
        raise NotImplementedError()
    elif type_ == 'datetime' and isinstance(value, datetime):
        return fields.Datetime.to_string(value)
    elif type_ == 'date' and isinstance(value, date):
        return fields.Date.to_string(value)
    return value


def get_static_context(context_str):
    """ Parse the given context string, and return the literal part of it. """
    context_ast = ast.parse(context_str.strip(), mode='eval').body
    assert isinstance(context_ast, ast.Dict)
    result = {}
    for key_ast, val_ast in zip(context_ast.keys, context_ast.values):
        try:
            key = ast.literal_eval(key_ast)
            val = ast.literal_eval(val_ast)
            result[key] = val
        except ValueError:
            pass
    return result


class Dotter:
    """ Simple wrapper for a dict where keys are accessed as readonly attributes. """
    __slots__ = ['__values']

    def __init__(self, values):
        self.__values = values

    def __getattr__(self, key):
        val = self.__values[key]
        return Dotter(val) if isinstance(val, dict) else val
