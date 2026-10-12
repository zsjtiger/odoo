"""Values of the x2many fields of a form: the records of one2many and many2many lines."""

from __future__ import annotations

import collections
import collections.abc
import itertools
from odoo.fields import Command


class UpdateDict(dict):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._changed = set()
        if args and isinstance(args[0], UpdateDict):
            self._changed.update(args[0]._changed)

    def __repr__(self):
        items = [
            f"{key!r}{'*' if key in self._changed else ''}: {val!r}"
            for key, val in self.items()
        ]
        return f"{{{', '.join(items)}}}"

    def changed_items(self):
        return (
            (k, v) for k, v in self.items()
            if k in self._changed
        )

    def update(self, *args, **kw):
        super().update(*args, **kw)
        if args and isinstance(args[0], UpdateDict):
            self._changed.update(args[0]._changed)

    def clear(self):
        super().clear()
        self._changed.clear()


class X2MValue(collections.abc.Sequence):
    """ The value of a one2many field, with the API of a sequence of record ids. """
    _virtual_seq = itertools.count()

    def __init__(self, iterable_of_vals=()):
        self._data = {vals['id']: UpdateDict(vals) for vals in iterable_of_vals}

    def __repr__(self):
        return repr(self._data)

    def __contains__(self, id_):
        return id_ in self._data

    def __getitem__(self, index):
        return list(self._data)[index]

    def __iter__(self):
        return iter(self._data)

    def __len__(self):
        return len(self._data)

    def __eq__(self, other):
        # this enables to compare self with a list
        return list(self) == other

    def get_vals(self, id_):
        return self._data[id_]

    def add(self, id_, vals):
        assert id_ not in self._data
        self._data[id_] = UpdateDict(vals)

    def remove(self, id_):
        self._data.pop(id_)

    def clear(self):
        self._data.clear()

    def create(self, vals):
        id_ = f'virtual_{next(self._virtual_seq)}'
        create_vals = UpdateDict(vals)
        create_vals._changed.update(vals)
        self._data[id_] = create_vals

    def update(self, id_, changes, changed=()):
        vals = self._data[id_]
        vals.update(changes)
        vals._changed.update(changed)

    def to_list_of_vals(self):
        return list(self._data.values())


class O2MValue(X2MValue):
    def __init__(self, iterable_of_vals=()):
        super().__init__(iterable_of_vals)
        self._given = list(self._data)

    def to_commands(self, convert_values=lambda vals: vals):
        given = set(self._given)
        result = []
        for id_, vals in self._data.items():
            if isinstance(id_, str) and id_.startswith('virtual_'):
                result.append((Command.CREATE, id_, convert_values(vals)))
                continue
            if id_ not in given:
                result.append(Command.link(id_))
            if vals._changed:
                result.append(Command.update(id_, convert_values(vals)))
        for id_ in self._given:
            if id_ not in self._data:
                result.append(Command.delete(id_))
        return result


class M2MValue(X2MValue):
    def __init__(self, iterable_of_vals=()):
        super().__init__(iterable_of_vals)
        self._given = list(self._data)

    def to_commands(self):
        given = set(self._given)
        result = []
        for id_, vals in self._data.items():
            if isinstance(id_, str) and id_.startswith('virtual_'):
                result.append((Command.CREATE, id_, {
                    key: val.to_commands() if isinstance(val, X2MValue) else val
                    for key, val in vals.changed_items()
                }))
                continue
            if id_ not in given:
                result.append(Command.link(id_))
            if vals._changed:
                result.append(Command.update(id_, {
                    key: val.to_commands() if isinstance(val, X2MValue) else val
                    for key, val in vals.changed_items()
                }))
        for id_ in self._given:
            if id_ not in self._data:
                result.append(Command.unlink(id_))
        return result
