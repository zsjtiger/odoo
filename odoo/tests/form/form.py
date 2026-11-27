"""The form: the simulation of the user editing a record in the tests."""

from __future__ import annotations

import ast
import logging
from lxml import etree
from odoo import api
from odoo.models import BaseModel
from .proxies import M2MProxy
from .values import UpdateDict


class Form:
    """ Server-side form view implementation (partial)

    Implements much of the "form view" manipulation flow, such that server-side
    tests can more properly reflect the behaviour which would be observed when
    manipulating the interface:

    * call the relevant onchanges on "creation";
    * call the relevant onchanges on setting fields;
    * properly handle defaults & onchanges around x2many fields.

    Saving the form returns the current record (which means the created record
    if in creation mode). It can also be accessed as ``form.record``, but only
    when the form has no pending changes.

    Regular fields can just be assigned directly to the form. In the case
    of :class:`~odoo.fields.Many2one` fields, one can assign a recordset::

        # empty recordset => creation mode
        f = Form(self.env['sale.order'])
        f.partner_id = a_partner
        so = f.save()

    One can also use the form as a context manager to create or edit a record.
    The changes are automatically saved at the end of the scope::

        with Form(self.env['sale.order']) as f1:
            f1.partner_id = a_partner
            # f1 is saved here

        # retrieve the created record
        so = f1.record

        # call Form on record => edition mode
        with Form(so) as f2:
            f2.payment_term_id = env.ref('account.account_payment_term_15days')
            # f2 is saved here

    For :class:`~odoo.fields.Many2many` fields, the field itself is a
    :class:`~odoo.tests.common.M2MProxy` and can be altered by adding or
    removing records::

        with Form(user) as u:
            u.group_ids.add(env.ref('account.group_account_manager'))
            u.group_ids.remove(id=env.ref('base.group_portal').id)

    Finally :class:`~odoo.fields.One2many` are reified as :class:`~O2MProxy`.

    Because the :class:`~odoo.fields.One2many` only exists through its parent,
    it is manipulated more directly by creating "sub-forms" with
    the :meth:`~O2MProxy.new` and :meth:`~O2MProxy.edit` methods. These would
    normally be used as context managers since they get saved in the parent
    record::

        with Form(so) as f3:
            f.partner_id = a_partner
            # add support
            with f3.order_line.new() as line:
                line.product_id = env.ref('product.product_product_2')
            # add a computer
            with f3.order_line.new() as line:
                line.product_id = env.ref('product.product_product_3')
            # we actually want 5 computers
            with f3.order_line.edit(1) as line:
                line.product_uom_qty = 5
            # remove support
            f3.order_line.remove(index=0)
            # SO is saved here

    :param record: empty or singleton recordset. An empty recordset will put
                   the view in "creation" mode from default values, while a
                   singleton will put it in "edit" mode and only load the
                   view's data.
    :param view: the id, xmlid or actual view object to use for onchanges and
                 view constraints. If none is provided, simply loads the
                 default view for the model.

    .. versionadded:: 12.0
    """
    def __init__(self, record: BaseModel, view: None | int | str | BaseModel = None) -> None:
        assert isinstance(record, BaseModel)
        assert len(record) <= 1

        # use object.__setattr__ to bypass Form's override of __setattr__
        object.__setattr__(self, '_record', record)
        object.__setattr__(self, '_env', record.env)

        # determine view and process it
        if isinstance(view, BaseModel):
            assert view._name == 'ir.ui.view', "the view parameter must be a view id, xid or record, got %s" % view
            view_id = view.id
        elif isinstance(view, str):
            view_id = record.env.ref(view).id
        else:
            view_id = view or False

        views = record.get_views([(view_id, 'form')])
        object.__setattr__(self, '_models_info', views['models'])
        # self._models_info = {model_name: {fields: {field_name: field_info}}}
        tree = etree.fromstring(views['views']['form']['arch'])
        view = self._process_view(tree, record)
        object.__setattr__(self, '_view', view)
        # self._view = {
        #     'tree': view_arch_etree,
        #     'fields': {field_name: field_info},
        #     'fields_spec': web_read_fields_spec,
        #     'modifiers': {field_name: {modifier: expression}},
        #     'contexts': {field_name: field_context_str},
        #     'onchange': onchange_spec,
        # }

        # determine record values
        object.__setattr__(self, '_values', UpdateDict())
        if record:
            self._init_from_record()
        else:
            self._init_from_defaults()
    @classmethod
    def from_action(cls, env: api.Environment, action: dict) -> Form:
        assert action['type'] == 'ir.actions.act_window', \
            f"only window actions are valid, got {action['type']}"
        # ensure the first-requested view is a form view
        if views := action.get('views'):
            assert views[0][1] == 'form', \
                f"the actions dict should have a form as first view, got {views[0][1]}"
            view_id = views[0][0]
        else:
            view_mode = action.get('view_mode', '')
            if not view_mode.startswith('form'):
                raise ValueError(f"The actions dict should have a form first view mode, got {view_mode}")
            view_id = action.get('view_id')
            if view_id and ',' in view_mode:
                raise ValueError(f"A `view_id` is only valid if the action has a single `view_mode`, got {view_mode}")
        context = action.get('context', {})
        if isinstance(context, str):
            context = ast.literal_eval(context)
        record = env[action['res_model']]\
            .with_context(context)\
            .browse(action.get('res_id'))

        return cls(record, view_id)
    def _process_view(self, tree, model, level=2):
        return _view._process_view(self, tree, model, level)
    def _get_one2many_edition_view(self, field_info, node, level):
        return _view._get_one2many_edition_view(self, field_info, node, level)
    def __str__(self):
        return f"<{type(self).__name__} {self._record}>"
    def _init_from_record(self):
        return _save._init_from_record(self)
    def _init_from_defaults(self):
        return _save._init_from_defaults(self)
    def __getattr__(self, field_name):
        """ Return the current value of the given field. """
        return self[field_name]
    def __getitem__(self, field_name):
        """ Return the current value of the given field. """
        field_info = self._view['fields'].get(field_name)
        assert field_info is not None, f"{field_name!r} was not found in the view"

        value = self._values[field_name]
        if field_info['type'] == 'many2one':
            Model = self._env[field_info['relation']]
            return Model.browse(value)
        elif field_info['type'] == 'one2many':
            return O2MProxy(self, field_name)
        elif field_info['type'] == 'many2many':
            return M2MProxy(self, field_name)
        return value
    def __setattr__(self, field_name, value):
        """ Set the given field to the given value, and proceed with the expected onchanges. """
        self[field_name] = value
    def __setitem__(self, field_name, value):
        """ Set the given field to the given value, and proceed with the expected onchanges. """
        field_info = self._view['fields'].get(field_name)
        assert field_info is not None, f"{field_name!r} was not found in the view"
        assert field_info['type'] != 'one2many', "Can't set an one2many field directly, use its proxy instead"
        assert not self._get_modifier(field_name, 'readonly'), f"can't write on readonly field {field_name!r}"
        assert not self._get_modifier(field_name, 'invisible'), f"can't write on invisible field {field_name!r}"

        if field_info['type'] == 'many2many':
            return M2MProxy(self, field_name).set(value)

        if field_info['type'] == 'many2one':
            assert isinstance(value, BaseModel) and value._name == field_info['relation']
            value = value.id

        self._values[field_name] = value
        self._perform_onchange(field_name)
    def _get_modifier(self, field_name, modifier, *, view=None, vals=None):
        return _modifiers._get_modifier(self, field_name, modifier, view=view, vals=vals)
    def _get_context(self, field_name):
        return _modifiers._get_context(self, field_name)
    def _get_eval_context(self, values=None):
        return _modifiers._get_eval_context(self, values)
    def _get_all_values(self):
        return _modifiers._get_all_values(self)
    def __enter__(self):
        """ This makes the Form usable as a context manager. """
        return self
    def __exit__(self, exc_type, exc_value, traceback):
        if not exc_type:
            self.save()
    def save(self):
        return _save.save(self)
    @property
    def record(self):
        """ Return the record being edited by the form. This attribute is
        readonly and can only be accessed when the form has no pending changes.
        """
        assert not self._values._changed
        return self._record
    def _get_save_values(self):
        return _save._get_save_values(self)
    def _get_values(self, mode, values=None, view=None, modifiers_values=None, parent_link=None):
        return _save._get_values(self, mode, values, view, modifiers_values, parent_link)
    def _perform_onchange(self, field_name=None):
        return _onchange._perform_onchange(self, field_name)
    def _get_onchange_values(self):
        return _onchange._get_onchange_values(self)
    def _apply_onchange(self, values):
        return _onchange._apply_onchange(self, values)
    def _apply_onchange_(self, values, fields, onchange_values):
        return _onchange._apply_onchange_(self, values, fields, onchange_values)


_logger = logging.getLogger('odoo.tests.form')


# the delegated methods of the class, and the modules that use the class: at the end, they import this module
from .o2m import O2MProxy  # noqa: E402
from . import view as _view, modifiers as _modifiers, onchange as _onchange, save as _save  # noqa: E402
