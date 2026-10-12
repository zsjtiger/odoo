"""The one2many form and proxy: the edition of the records of a one2many field in a form."""

from __future__ import annotations

from .proxies import X2MProxy
from .utils import Dotter
from .values import UpdateDict

from .form import Form

class O2MForm(Form):
    # noinspection PyMissingConstructor
    # pylint: disable=super-init-not-called
    def __init__(self, proxy, index=None):
        model = proxy._model
        object.__setattr__(self, '_proxy', proxy)
        object.__setattr__(self, '_index', index)

        object.__setattr__(self, '_record', model)
        object.__setattr__(self, '_env', model.env)

        object.__setattr__(self, '_models_info', proxy._form._models_info)
        object.__setattr__(self, '_view', proxy._field_info['edition_view'])

        object.__setattr__(self, '_values', UpdateDict())
        if index is None:
            self._init_from_defaults()
        else:
            vals = proxy._records[index]
            self._values.update(vals)
            if vals.get('id'):
                object.__setattr__(self, '_record', model.browse(vals['id']))

    def _get_modifier(self, field_name, modifier, *, view=None, vals=None):
        if modifier != 'required' and self._proxy._form._get_modifier(self._proxy._field, modifier):
            return True
        return super()._get_modifier(field_name, modifier, view=view, vals=vals)

    def _get_eval_context(self, values=None):
        eval_context = super()._get_eval_context(values)
        eval_context['parent'] = Dotter(self._proxy._form._values)
        return eval_context

    def _get_onchange_values(self):
        values = super()._get_onchange_values()
        # computed o2m may not have a relation_field(?)
        field_info = self._proxy._field_info
        if 'relation_field' in field_info:  # note: should be fine because not recursive
            parent_form = self._proxy._form
            parent_values = parent_form._get_onchange_values()
            if parent_form._record.id:
                parent_values['id'] = parent_form._record.id
            values[field_info['relation_field']] = parent_values
        return values

    def save(self):
        proxy = self._proxy
        field_value = proxy._form._values[proxy._field]
        values = self._get_save_values()
        if self._index is None:
            field_value.create(values)
        else:
            id_ = field_value[self._index]
            field_value.update(id_, values)

        proxy._form._perform_onchange(proxy._field)

    def _get_save_values(self):
        """ Validate and return field values modified since load/save. """
        values = UpdateDict(self._values)

        for field_name in self._view['fields']:
            if self._get_modifier(field_name, 'required') and not (
                self._get_modifier(field_name, 'column_invisible')
                or self._get_modifier(field_name, 'invisible')
            ):
                assert values[field_name] is not False, f"{field_name!r} is a required field"

        return values


class O2MProxy(X2MProxy):
    """ Proxy object for editing the value of a one2many field. """
    def __len__(self):
        return len(self._field_value)

    @property
    def _model(self):
        model = self._form._env[self._field_info['relation']]
        context = self._form._get_context(self._field)
        if context:
            model = model.with_context(**context)
        return model

    @property
    def _records(self):
        return self._field_value.to_list_of_vals()

    def new(self):
        """ Returns a :class:`Form` for a new
        :class:`~odoo.fields.One2many` record, properly initialised.

        The form is created from the list view if editable, or the field's
        form view otherwise.

        :raises AssertionError: if the field is not editable
        """
        self._assert_editable()
        return O2MForm(self)

    def edit(self, index):
        """ Returns a :class:`Form` to edit the pre-existing
        :class:`~odoo.fields.One2many` record.

        The form is created from the list view if editable, or the field's
        form view otherwise.

        :raises AssertionError: if the field is not editable
        """
        self._assert_editable()
        return O2MForm(self, index)

    def remove(self, index):
        """ Removes the record at ``index`` from the parent form.

        :raises AssertionError: if the field is not editable
        """
        self._assert_editable()
        self._field_value.remove(self._field_value[index])
        self._form._perform_onchange(self._field)
