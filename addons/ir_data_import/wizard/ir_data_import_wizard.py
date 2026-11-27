# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import AccessError, UserError


class IrDataImportWizard(models.TransientModel):
    """Import dialog: download the template, upload a file, validate, then import."""
    _name = 'ir.data.import.wizard'
    _description = 'Data Import'

    model_id = fields.Many2one('ir.model', required=True, readonly=True)
    model_name = fields.Char(related='model_id.model', readonly=True)
    has_record_types = fields.Boolean(compute='_compute_has_record_types')
    record_type_id = fields.Many2one(
        'ir.record.type', string='Record type',
        domain="[('model_id', '=', model_id)]",
        help='Downloads the template of this type, and is the default for new rows without a record type.',
    )
    file = fields.Binary(string='Excel file', attachment=False)
    filename = fields.Char()
    state = fields.Selection([('upload', 'Upload'), ('validated', 'Validated'), ('done', 'Done')],
                             default='upload', readonly=True)
    job_id = fields.Many2one('ir.data.import.job', readonly=True)
    total_rows = fields.Integer(related='job_id.total_rows')
    error_rows = fields.Integer(related='job_id.error_rows')
    created_rows = fields.Integer(related='job_id.created_rows')
    updated_rows = fields.Integer(related='job_id.updated_rows')
    deleted_rows = fields.Integer(related='job_id.deleted_rows')
    message = fields.Text(related='job_id.message')
    result_file = fields.Binary(related='job_id.result_file')
    result_filename = fields.Char(related='job_id.result_filename')

    @api.depends('model_id')
    def _compute_has_record_types(self):
        for wizard in self:
            wizard.has_record_types = bool(wizard.model_id.sudo().supports_record_type)

    def _check_template_or_import(self):
        perm = self.env['ir.data.import.permission']
        if not (perm._user_can(self.model_name, 'perm_template') or perm._user_can(self.model_name, 'allow_import')):
            raise AccessError(_('You are not allowed to use the import of %s.', self.model_id.name))

    def action_download_template(self):
        self.ensure_one()
        self._check_template_or_import()
        return self.env['ir.data.import.template']._download_template(self.model_name, self.record_type_id or None)

    def action_validate(self):
        self.ensure_one()
        if not self.file:
            raise UserError(_('Choose an Excel file first.'))
        job = self.env['ir.data.import.job'].create({
            'model_id': self.model_id.id,
            'source_file': self.file,
            'source_filename': self.filename,
            'record_type_id': self.record_type_id.id or False,
        })
        job.action_validate()
        self.write({'job_id': job.id, 'state': 'validated'})
        return self._reopen()

    def action_import(self):
        self.ensure_one()
        if not self.job_id:
            raise UserError(_('Validate the file first.'))
        self.job_id.action_import()
        if self.job_id.state == 'done':
            self.state = 'done'
        return self._reopen()

    def action_new_file(self):
        self.ensure_one()
        self.write({'file': False, 'filename': False, 'job_id': False, 'state': 'upload'})
        return self._reopen()

    def _reopen(self):
        return {
            'type': 'ir.actions.act_window',
            'name': _('Import'),
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }
