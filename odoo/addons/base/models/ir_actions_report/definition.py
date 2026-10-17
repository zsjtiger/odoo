# Part of Odoo. See LICENSE file for full copyright and licensing details.
"""The definition of the report actions: the fields, the links to the views and the models, the actions and the paper formats."""

import json
import re
from ast import literal_eval
from odoo import models
from odoo.fields import Domain

from .report import IrActionsReport

def _compute_linked_view_ids(self):
    suffixes = {action: action.report_name.split('.')[1] for action in self if '.' in (action.report_name or '')}
    views = self.env['ir.ui.view'].search(Domain('type', '=', 'qweb') & Domain.OR(Domain('name', 'ilike', suffix) for suffix in suffixes.values()))
    for action in self:
        action.linked_view_ids = views.filtered_domain(Domain('name', 'ilike', suffixes.get(action))) if suffixes.get(action) else views.browse()
        action.linked_view_count = len(action.linked_view_ids)


def _compute_model_id(self):
    for action in self:
        action.model_id = self.env['ir.model']._get(action.model).id


def _onchange_model_id(self):
    for action in self:
        action.model = action.model_id.model


def _onchange_name(self):
    for action in self.filtered(lambda a: not a._origin and a.name):
        name = re.sub(r'[^a-z0-9_]', '', action.name.replace(' ', '_').lower())
        action.report_name = "report_name." + name


def _search_model_id(self, operator, value):
    if operator in Domain.NEGATIVE_OPERATORS:
        return NotImplemented
    models = self.env['ir.model']
    if isinstance(value, str):
        models = models.search(Domain('display_name', operator, value))
    elif isinstance(value, Domain):
        models = models.search(value)
    elif operator == 'any!':
        models = models.sudo().search(Domain('id', operator, value))
    elif operator == 'any' or isinstance(value, int):
        models = models.search(Domain('id', operator, value))
    elif operator == 'in':
        models = models.search(Domain.OR(
            Domain('id' if isinstance(v, int) else 'display_name', operator, v)
            for v in value
            if v
        ))
    return Domain('model', 'in', models.mapped('model'))


def _get_readable_fields(self):
    return super(IrActionsReport, self)._get_readable_fields() | {
        "report_name", "report_type", "target",
        # these two are not real fields of ir.actions.report but are
        # expected in the route /report/<converter>/<reportname> and must
        # not be removed by clean_action
        "context", "data",
        # and this one is used by the frontend later on.
        "close_on_report_download",
        "domain",
    }


def associated_view(self):
    """Used in the ir.actions.report form view in order to search naively after the view(s)
        used in the rendering.
        """
    self.ensure_one()
    return self.linked_view_ids._get_records_action()


def create_action(self):
    """ Create a contextual action for each report. """
    for report in self:
        model = self.env['ir.model']._get(report.model)
        report.write({'binding_model_id': model.id, 'binding_type': 'report'})
    return True


def unlink_action(self):
    """ Remove the contextual actions created for the reports. """
    self.check_access('write')
    self.filtered('binding_model_id').write({'binding_model_id': False})
    return True


def get_paperformat(self):
    return self.paperformat_id or self.env.company.paperformat_id


def get_paperformat_by_xmlid(self, xml_id):
    return self.env.ref(xml_id).get_paperformat() if xml_id else self.env.company.paperformat_id


def _get_report_from_name(self, report_name):
    """Get the first record of ir.actions.report having the ``report_name`` as value for
        the field report_name.
        """
    report_obj = self.env['ir.actions.report']
    conditions = [('report_name', '=', report_name)]
    context = self.env['res.users'].context_get()
    return report_obj.with_context(context).sudo().search(conditions, limit=1)


def _get_report(self, report_ref):
    """Get the report (with sudo) from a reference

        :param report_ref: can be one of

            - ir.actions.report id
            - ir.actions.report record
            - ir.model.data reference to ir.actions.report
            - ir.actions.report report_name
        """
    ReportSudo = self.env['ir.actions.report'].sudo()
    if isinstance(report_ref, int):
        return ReportSudo.browse(report_ref)
    if isinstance(report_ref, models.Model):
        if report_ref._name != self._name:
            raise ValueError("Expected report of type %s, got %s" % (self._name, report_ref._name))
        return report_ref.sudo()
    report = ReportSudo.search([('report_name', '=', report_ref)], limit=1)
    if report:
        return report
    report = self.env.ref(report_ref)
    if report:
        if report._name != "ir.actions.report":
            raise ValueError("Fetching report %r: type %s, expected ir.actions.report" % (report_ref, report._name))
        return report.sudo()
    raise ValueError("Fetching report %r: report not found" % report_ref)


def report_action(self, docids, data=None, config=True):
    """Return an action of type ir.actions.report.

        :param docids: id/ids/browse record of the records to print (if not used, pass an empty list)
        :param data:
        :param bool config:
        :rtype: bytes
        """
    context = self.env.context
    if docids:
        if isinstance(docids, models.Model):
            active_ids = docids.ids
        elif isinstance(docids, int):
            active_ids = [docids]
        elif isinstance(docids, list):
            active_ids = docids
        context = dict(self.env.context, active_ids=active_ids)

    report_action = {
        'context': context,
        'data': data,
        'type': 'ir.actions.report',
        'report_name': self.report_name,
        'report_type': self.report_type,
        'name': self.name,
    }

    discard_logo_check = self.env.context.get('discard_logo_check')
    if self.env.is_admin() and not self.env.company.external_report_layout_id and config and not discard_logo_check:
        return self._action_configure_external_report_layout(report_action)

    return report_action


def _action_configure_external_report_layout(self, report_action, xml_id="web.action_base_document_layout_configurator"):
    action = self.env["ir.actions.actions"]._for_xml_id(xml_id)
    py_ctx = json.loads(action.get('context', {}))
    report_action['close_on_report_download'] = True
    py_ctx['report_action'] = report_action
    action['context'] = py_ctx
    return action


def get_valid_action_reports(self, model, record_ids):
    """ Return the list of ids of actions for which the domain is
        satisfied by at least one record in record_ids.
        :param model: the model of the records to validate
        :param record_ids: list of ids of records to validate
        """
    records = self.env[model].browse(record_ids)
    actions_with_domain = self.filtered('domain')
    valid_action_report_ids = (self - actions_with_domain).ids  # actions without domain are always valid
    for action in actions_with_domain:
        if records.filtered_domain(literal_eval(action.domain)):
            valid_action_report_ids.append(action.id)
    return valid_action_report_ids
