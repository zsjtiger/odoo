# Part of Odoo. See LICENSE file for full copyright and licensing details.
"""The report actions (ir.actions.report): the model and its fields. The methods are split by concern in the other modules of this package."""

import logging
import typing
from collections.abc import Sequence
from PIL import ImageFile
from odoo import api, fields, models


_logger = logging.getLogger('odoo.addons.base.models.ir_actions_report')


class IrActionsReport(models.Model):
    _name = 'ir.actions.report'
    _description = 'Report Action'
    _inherit = ['ir.actions.actions']
    _table = 'ir_act_report_xml'
    _order = 'name, id'
    _allow_sudo_commands = False
    type = fields.Char(default='ir.actions.report')
    binding_type = fields.Selection(default='report')
    model = fields.Char(required=True, string='Model Name')
    model_id = fields.Many2one('ir.model', string='Model', compute='_compute_model_id', search='_search_model_id')
    report_type = fields.Selection([
        ('qweb-html', 'HTML'),
        ('qweb-pdf', 'PDF'),
        ('qweb-text', 'Text'),
    ], required=True, default='qweb-pdf', string="Format",
    help='The type of the report that will be rendered, each one having its own'
        ' rendering method. HTML means the report will be opened directly in your'
        ' browser, PDF means the report will be generated and'
        ' downloaded by the user.')
    report_name = fields.Char(string='Technical Name', required=True)
    group_ids = fields.Many2many('res.groups', 'res_groups_report_rel', 'uid', 'gid', string='Groups')
    multi = fields.Boolean(string='On Multiple Doc.', help="If set to true, the action will not be displayed on the right toolbar of a form view.")
    paperformat_id = fields.Many2one('report.paperformat', 'Paper Size', index='btree_not_null')
    print_report_name = fields.Char('Printed Report Name', translate=True,
                                    help="This is the filename of the report going to download. Keep empty to not change the report filename. You can use a python expression with the 'object' and 'time' variables.")
    save_as_attachment = fields.Boolean(help='Whether the report is saved as attachment when it is printed')
    attachment_use = fields.Boolean(string='Generate new file each time the report is printed',
                                    help='If enabled, then the second time the user prints with same attachment name, it returns the previous report.')
    attachment = fields.Char(string='Attachment Name',
                             help='This is the filename of the attachment used to store the printing result. Keep empty to not save the printed reports. You can use a python expression with the object and time variables.')
    domain = fields.Char(string='Domain', help='If set, the action will only appear on records that matches the domain.')
    linked_view_ids = fields.Many2many('ir.ui.view', compute='_compute_linked_view_ids')
    linked_view_count = fields.Integer(compute='_compute_linked_view_ids')
    @api.depends('report_name')
    def _compute_linked_view_ids(self):
        return _definition._compute_linked_view_ids(self)
    @api.depends('model')
    def _compute_model_id(self):
        return _definition._compute_model_id(self)
    @api.onchange('model_id')
    def _onchange_model_id(self):
        return _definition._onchange_model_id(self)
    @api.onchange('name')
    def _onchange_name(self):
        return _definition._onchange_name(self)
    def _search_model_id(self, operator, value):
        return _definition._search_model_id(self, operator, value)
    def _get_readable_fields(self):
        return _definition._get_readable_fields(self)
    def associated_view(self):
        return _definition.associated_view(self)
    def create_action(self):
        return _definition.create_action(self)
    def unlink_action(self):
        return _definition.unlink_action(self)
    def retrieve_attachment(self, record):
        return _render_pdf.retrieve_attachment(self, record)
    @api.model
    def get_pdf_engine_state(self, engine_name) -> typing.Literal['ok', 'upgrade', 'workers', 'broken', 'install']:
        return _render_pdf.get_pdf_engine_state(self, engine_name)
    def get_paperformat(self):
        return _definition.get_paperformat(self)
    def get_paperformat_by_xmlid(self, xml_id):
        return _definition.get_paperformat_by_xmlid(self, xml_id)
    def _get_layout(self):
        return _render_html._get_layout(self)
    def _get_report_url(self, layout=None):
        return _render_html._get_report_url(self, layout)
    def _prepare_html(self, html, report_model=False):
        return _render_html._prepare_html(self, html, report_model)
    @api.model
    def _get_report_from_name(self, report_name):
        return _definition._get_report_from_name(self, report_name)
    @api.model
    def _get_report(self, report_ref):
        return _definition._get_report(self, report_ref)
    @api.model
    def barcode(self, barcode_type, value, **kwargs):
        return _render_html.barcode(self, barcode_type, value, **kwargs)
    @api.model
    def get_available_barcode_masks(self):
        return _render_html.get_available_barcode_masks(self)
    def _render_template(self, template, values=None):
        return _render_html._render_template(self, template, values)
    def _handle_merge_pdfs_error(self, error=None, error_stream=None):
        return _render_pdf._handle_merge_pdfs_error(self, error, error_stream)
    @api.model
    def _merge_pdfs(self, streams, handle_error=None):
        return _render_pdf._merge_pdfs(self, streams, handle_error)
    def _render_qweb_pdf_prepare_streams(self, report_ref, data, res_ids=None):
        return _render_pdf._render_qweb_pdf_prepare_streams(self, report_ref, data, res_ids)
    def _prepare_pdf_report_attachment_vals_list(self, report, streams):
        return _render_pdf._prepare_pdf_report_attachment_vals_list(self, report, streams)
    def _pre_render_qweb_pdf(self, report_ref, res_ids=None, data=None):
        return _render_pdf._pre_render_qweb_pdf(self, report_ref, res_ids, data)
    def _render_qweb_pdf(self, report_ref, res_ids=None, data=None):
        return _render_pdf._render_qweb_pdf(self, report_ref, res_ids, data)
    @api.model
    def _render_qweb_text(self, report_ref, docids, data=None):
        return _render_html._render_qweb_text(self, report_ref, docids, data)
    @api.model
    def _render_qweb_html(self, report_ref, docids, data=None):
        return _render_html._render_qweb_html(self, report_ref, docids, data)
    def _get_rendering_context_model(self, report):
        return _render_html._get_rendering_context_model(self, report)
    def _get_rendering_context(self, report, docids, data):
        return _render_html._get_rendering_context(self, report, docids, data)
    def _get_pdf_engine(self, report=None, default_engine='wkhtmltopdf') -> str:
        return _render_pdf._get_pdf_engine(self, report, default_engine)
    def _run_image_engine(self, engine_name: str, bodies: Sequence[str], width: int, height: int, image_format: str='jpg') -> list[bytes | None]:
        return _render_pdf._run_image_engine(self, engine_name, bodies, width, height, image_format)
    @api.model
    def _run_pdf_engine(self, engine_name: str, html: str, report_ref: str | typing.Literal[False]=False, landscape: bool=False, **kwargs) -> tuple[bytes, list[int]]:
        return _render_pdf._run_pdf_engine(self, engine_name, html, report_ref, landscape, **kwargs)
    @api.model
    def _run_pdf_engine_without_processing(self, engine_name: str, bodies: Sequence[str], report_ref: str | typing.Literal[False]=False, *, header: str | None=None, footer: str | None=None, landscape: bool=False, specific_paperformat_args: dict | None=None, **kwargs) -> bytes:
        return _render_pdf._run_pdf_engine_without_processing(self, engine_name, bodies, report_ref, header=header, footer=footer, landscape=landscape, specific_paperformat_args=specific_paperformat_args, **kwargs)
    @api.model
    def _render(self, report_ref, res_ids, data=None):
        return _render_pdf._render(self, report_ref, res_ids, data)
    def report_action(self, docids, data=None, config=True):
        return _definition.report_action(self, docids, data, config)
    def _action_configure_external_report_layout(self, report_action, xml_id='web.action_base_document_layout_configurator'):
        return _definition._action_configure_external_report_layout(self, report_action, xml_id)
    def get_valid_action_reports(self, model, record_ids):
        return _definition.get_valid_action_reports(self, model, record_ids)
    @api.model
    def _prepare_local_attachments(self, attachments):
        return _render_pdf._prepare_local_attachments(self, attachments)


ImageFile.LOAD_TRUNCATED_IMAGES = True


# the delegated methods of the class, and the modules that use the class: at the end, they import this module
from . import definition as _definition, render_html as _render_html, render_pdf as _render_pdf  # noqa: E402
