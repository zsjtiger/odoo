"""Proxies of the x2many fields of a form, that record the changes of the lines."""

from __future__ import annotations

import collections.abc
from odoo.models import BaseModel


class X2MProxy:
    """ A proxy represents the value of an x2many field, but not directly.
    Instead, it provides an API to add, remove or edit records in the value.
    """
    _form = None        # Form containing the corresponding x2many field
    _field = None       # name of the x2many field
    _field_info = None  # field info

    def __init__(self, form, field_name):
        self._form = form
        self._field = field_name
        self._field_info = form._view['fields'][field_name]
        self._field_value = form._values[field_name]

    @property
    def ids(self):
        return list(self._field_value)

    def _assert_editable(self):
        assert not self._form._get_modifier(self._field, 'readonly'), f'field {self._field!r} is not editable'
        assert not self._form._get_modifier(self._field, 'invisible'), f'field {self._field!r} is not visible'


class M2MProxy(X2MProxy, collections.abc.Sequence):
    """ Proxy object for editing the value of a many2many field.

    Behaves as a :class:`~collection.Sequence` of recordsets, can be
    indexed or sliced to get actual underlying recordsets.
    """
    def __getitem__(self, index):
        comodel_name = self._field_info['relation']
        return self._form._env[comodel_name].browse(self._field_value[index])

    def __len__(self):
        return len(self._field_value)

    def __iter__(self):
        comodel_name = self._field_info['relation']
        records = self._form._env[comodel_name].browse(self._field_value)
        return iter(records)

    def __contains__(self, record):
        comodel_name = self._field_info['relation']
        assert isinstance(record, BaseModel) and record._name == comodel_name
        return record.id in self._field_value

    def add(self, record):
        """ Adds ``record`` to the field, the record must already exist.

        The addition will only be finalized when the parent record is saved.
        """
        self._assert_editable()
        parent = self._form
        comodel_name = self._field_info['relation']
        assert isinstance(record, BaseModel) and record._name == comodel_name, \
            f"trying to assign a {record._name!r} object to a {comodel_name!r} field"

        if record.id not in self._field_value:
            self._field_value.add(record.id, {'id': record.id})
            parent._perform_onchange(self._field)

    # pylint: disable=redefined-builtin
    def remove(self, id=None, index=None):
        """ Removes a record at a certain index or with a provided id from
        the field.
        """
        self._assert_editable()
        assert (id is None) ^ (index is None), "can remove by either id or index"
        if id is None:
            id = self._field_value[index]
        self._field_value.remove(id)
        self._form._perform_onchange(self._field)

    def set(self, records):
        """ Set the field value to be ``records``. """
        self._assert_editable()
        comodel_name = self._field_info['relation']
        assert isinstance(records, BaseModel) and records._name == comodel_name, \
            f"trying to assign a {records._name!r} object to a {comodel_name!r} field"

        if set(records.ids) != set(self._field_value):
            self._field_value.clear()
            for id_ in records.ids:
                self._field_value.add(id_, {'id': id_})
            self._form._perform_onchange(self._field)

    def clear(self):
        """ Removes all existing records in the m2m
        """
        self._assert_editable()
        self._field_value.clear()
        self._form._perform_onchange(self._field)
