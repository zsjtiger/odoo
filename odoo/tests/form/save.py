"""The saving of the form: the values to write, and the initialization of the values from the record or the defaults."""

from __future__ import annotations

from .utils import Dotter, convert_read_to_form
from .values import UpdateDict


def _init_from_record(self):
    """ Initialize the form for an existing record. """
    assert self._record.id, "editing unstored records is not supported"
    self._values.clear()

    [record_values] = self._record.web_read(self._view['fields_spec'])
    self._env.flush_all()
    self._env.transaction.clear()

    values = convert_read_to_form(record_values, self._view['fields'])
    self._values.update(values)


def _init_from_defaults(self):
    """ Initialize the form for a new record. """
    vals = self._values
    vals['id'] = False

    # call onchange with no field; this retrieves default values, applies
    # onchanges and return the result
    self._perform_onchange()
    # mark all fields as modified
    self._values._changed.update(self._view['fields'])


def save(self):
    """ Save the form (if necessary) and return the current record:

    * does not save ``readonly`` fields;
    * does not save unmodified fields (during edition) — any assignment
      or onchange return marks the field as modified, even if set to its
      current value.

    When nothing must be saved, it simply returns the current record.

    :raises AssertionError: if the form has any unfilled required field
    """
    values = self._get_save_values()
    if not self._record or values:
        # save and reload
        [record_values] = self._record.web_save(values, self._view['fields_spec'])
        self._env.flush_all()
        self._env.transaction.clear()  # discard cache and pending recomputations

        if not self._record:
            record = self._record.browse(record_values['id'])
            object.__setattr__(self, '_record', record)

        values = convert_read_to_form(record_values, self._view['fields'])
        self._values.clear()
        self._values.update(values)

    return self._record


def _get_save_values(self):
    """ Validate and return field values modified since load/save. """
    return self._get_values('save')


def _get_values(self, mode, values=None, view=None, modifiers_values=None, parent_link=None):
    """ Validate & extract values, recursively in order to handle o2ms properly.

    :param mode: can be ``"save"`` (validate and return non-readonly modified fields),
        ``"onchange"`` (return modified fields) or ``"all"`` (return all field values)
    :param UpdateDict values: values of the record to extract
    :param view: view info
    :param dict modifiers_values: defaults to ``values``, but o2ms need some additional massaging
    :param parent_link: optional field representing "parent"
    """
    assert mode in ('save', 'onchange', 'all')

    if values is None:
        values = self._values
    if view is None:
        view = self._view
    assert isinstance(values, UpdateDict)

    modifiers_values = modifiers_values or values

    result = {}
    for field_name, field_info in view['fields'].items():
        if field_name == 'id' or field_name not in values:
            continue

        value = values[field_name]

        # note: maybe `invisible` should not skip `required` if model attribute
        if (
            mode == 'save'
            and value is False
            and field_name != parent_link
            and field_info['type'] != 'boolean'
            and not self._get_modifier(field_name, 'invisible', view=view, vals=modifiers_values)
            and not self._get_modifier(field_name, 'column_invisible', view=view, vals=modifiers_values)
            and self._get_modifier(field_name, 'required', view=view, vals=modifiers_values)
        ):
            raise AssertionError(f"{field_name} is a required field ({view['modifiers'][field_name]})")

        # skip unmodified fields unless all_fields
        if mode in ('save', 'onchange') and field_name not in values._changed:
            continue

        if mode == 'save' and self._get_modifier(field_name, 'readonly', view=view, vals=modifiers_values):
            field_node = next(
                node
                for node in view['tree'].iter('field')
                if node.get('name') == field_name
            )
            if not field_node.get('force_save'):
                continue

        if field_info['type'] == 'one2many':
            if mode == 'all':
                # in the context of an eval, format it as a list of ids
                value = list(value)
            else:
                subview = field_info['edition_view']
                value = value.to_commands(lambda vals: self._get_values(
                    mode, vals, subview,
                    modifiers_values={'id': False, **vals, 'parent': Dotter(values)},
                    # related o2m don't have a relation_field
                    parent_link=field_info.get('relation_field'),
                ))

        elif field_info['type'] == 'many2many':
            if mode == 'all':
                # in the context of an eval, format it as a list of ids
                value = list(value)
            else:
                value = value.to_commands()

        elif field_info['type'] == 'binary':
            if isinstance(value, dict) and 'content' not in value:
                # field is just read and not modified
                continue

        result[field_name] = value

    return result
