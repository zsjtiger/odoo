"""The modifiers of the fields in the form: their attributes, their context and their evaluation."""

from __future__ import annotations

from datetime import date
from odoo.tools.safe_eval import safe_eval


def _get_modifier(self, field_name, modifier, *, view=None, vals=None):
    if view is None:
        view = self._view

    expr = view['modifiers'][field_name].get(modifier, False)
    if isinstance(expr, bool):
        return expr
    if expr in ('True', 'False'):
        return expr == 'True'

    if vals is None:
        vals = self._values

    eval_context = self._get_eval_context(vals)

    return bool(safe_eval(expr, eval_context))


def _get_context(self, field_name):
    """ Return the context of a given field. """
    context_str = self._view['contexts'].get(field_name)
    if not context_str:
        return {}
    eval_context = self._get_eval_context()
    return safe_eval(context_str, eval_context)


def _get_eval_context(self, values=None):
    """ Return the context dict to eval something. """
    context = {
        'id': self._record.id,
        'active_id': self._record.id,
        'active_ids': self._record.ids,
        'active_model': self._record._name,
        'current_date': date.today().strftime("%Y-%m-%d"),
        **self._env.context,
    }
    if values is None:
        values = self._get_all_values()
    return {
        **context,
        'context': context,
        **values,
    }


def _get_all_values(self):
    """ Return the values of all fields. """
    return self._get_values('all')
