"""The onchanges of the form: their values and their application."""

from __future__ import annotations

import collections.abc
from odoo.fields import Command
from .utils import _cleanup_from_default, convert_read_to_form
from .values import UpdateDict

from .form import _logger

def _perform_onchange(self, field_name=None):
    assert field_name is None or isinstance(field_name, str)

    # marks onchange source as changed
    if field_name:
        field_names = [field_name]
        self._values._changed.add(field_name)
    else:
        field_names = []

    # skip calling onchange() if there's no on_change on the field
    if field_name and not self._view['onchange'][field_name]:
        return

    record = self._record

    # if the onchange is triggered by a field, add the context of that field
    if field_name:
        context = self._get_context(field_name)
        if context:
            record = record.with_context(**context)

    values = self._get_onchange_values()
    result = record.onchange(values, field_names, self._view['fields_spec'])
    self._env.flush_all()
    self._env.transaction.clear()  # discard cache and pending recomputations

    if w := result.get('warning'):
        if isinstance(w, collections.abc.Mapping) and w.keys() >= {'title', 'message'}:
            _logger.getChild('onchange').warning("%(title)s %(message)s", w)
        else:
            _logger.getChild('onchange').error(
                "received invalid warning %r from onchange on %r (should be a dict with keys `title` and `message`)",
                w,
                field_names,
            )

    if not field_name:
        # fill in whatever fields are still missing with falsy values
        self._values.update({
            field_name: _cleanup_from_default(field_info['type'], False)
            for field_name, field_info in self._view['fields'].items()
            if field_name not in self._values
        })

    if result.get('value'):
        self._apply_onchange(result['value'])

    return result


def _get_onchange_values(self):
    """ Return modified field values for onchange. """
    return self._get_values('onchange')


def _apply_onchange(self, values):
    self._apply_onchange_(self._values, self._view['fields'], values)


def _apply_onchange_(self, values, fields, onchange_values):
    assert isinstance(values, UpdateDict)
    for fname, value in onchange_values.items():
        field_info = fields[fname]
        if field_info['type'] in ('one2many', 'many2many'):
            subfields = {}
            if field_info['type'] == 'one2many':
                subfields = field_info['edition_view']['fields']
            field_value = values[fname]
            for cmd in value:
                match cmd[0]:
                    case Command.CREATE:
                        vals = UpdateDict(convert_read_to_form(dict.fromkeys(subfields, False), subfields))
                        self._apply_onchange_(vals, subfields, cmd[2])
                        field_value.create(vals)
                    case Command.UPDATE:
                        vals = field_value.get_vals(cmd[1])
                        self._apply_onchange_(vals, subfields, cmd[2])
                    case Command.DELETE | Command.UNLINK:
                        field_value.remove(cmd[1])
                    case Command.LINK:
                        field_value.add(cmd[1], convert_read_to_form(cmd[2], subfields))
                    case c:
                        raise ValueError(f"Unexpected onchange() o2m command {c!r}")
        else:
            values[fname] = value
        values._changed.add(fname)
