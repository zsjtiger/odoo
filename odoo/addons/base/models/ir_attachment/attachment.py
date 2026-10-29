# Part of Odoo. See LICENSE file for full copyright and licensing details.
"""The attachments (ir.attachment): the model, its fields and its constraints. The methods are split by concern in the other modules of this package."""

from __future__ import annotations

import io
import logging
import typing
from odoo import api, fields, models
from odoo.tools.files.binary import BinaryValue

if typing.TYPE_CHECKING:
    from collections.abc import Collection


_logger = logging.getLogger('odoo.addons.base.models.ir_attachment')


class IrAttachment(models.Model):
    """Attachments are used to link binary files or url to any openerp document.

    External attachment storage
    ---------------------------

    The computed field ``raw`` is implemented using ``_file_read``,
    ``_file_write`` and ``_file_delete``, which can be overridden to implement
    other storage engines. Such methods should check for other location pseudo
    uri (example: hdfs://hadoopserver).

    The default implementation is the file:dirname location that stores files
    on the local filesystem using name based on their sha1 hash
    """
    _name = 'ir.attachment'
    _description = 'Attachment'
    _order = 'id desc'
    _access_domain_heavy = True
    def _compute_res_name(self):
        return _access._compute_res_name(self)
    @api.model
    def _storage(self):
        return _storage._storage(self)
    @api.model
    def _filestore(self):
        return _storage._filestore(self)
    @api.model
    def _get_storage_domain(self):
        return _storage._get_storage_domain(self)
    @api.model
    def force_storage(self):
        return _storage.force_storage(self)
    def _migrate(self):
        return _storage._migrate(self)
    @api.model
    def _full_path(self, path):
        return _storage._full_path(self, path)
    @api.model
    def _file_fname(self, sha: str) -> str:
        return _storage._file_fname(self, sha)
    def _file_read(self) -> BinaryValue:
        return _storage._file_read(self)
    @api.model
    def _file_write(self, fname: str, bin_value: io.IOBase) -> None:
        return _storage._file_write(self, fname, bin_value)
    @api.model
    def _file_delete(self, fname: str) -> None:
        return _storage._file_delete(self, fname)
    def _mark_for_gc(self, fname: str) -> None:
        return _storage._mark_for_gc(self, fname)
    @api.autovacuum
    def _gc_file_store(self):
        return _storage._gc_file_store(self)
    def _gc_file_store_unsafe(self, grace_period):
        return _storage._gc_file_store_unsafe(self, grace_period)
    @api.depends('store_fname', 'db_datas', 'name')
    def _compute_raw(self):
        return _content._compute_raw(self)
    def _get_pdf_raw(self):
        return _content._get_pdf_raw(self)
    def _inverse_raw(self):
        return _content._inverse_raw(self)
    def _get_datas_related_values(self, data: BinaryValue, mimetype):
        return _content._get_datas_related_values(self, data, mimetype)
    @api.model
    def _compute_checksum(self, bin_data):
        return _content._compute_checksum(self, bin_data)
    @api.model
    def _same_content(self, file1: io.IOBase, file2: io.IOBase) -> bool:
        return _content._same_content(self, file1, file2)
    def _compute_mimetype(self, values):
        return _content._compute_mimetype(self, values)
    @api.model
    def _postprocess_contents(self, values):
        return _content._postprocess_contents(self, values)
    @api.model
    def _check_contents(self, values):
        return _content._check_contents(self, values)
    @api.model
    def _index(self, bin_data: BinaryValue, file_type: str, checksum=None) -> str | None:
        return _content._index(self, bin_data, file_type, checksum)
    @api.model
    def get_serving_groups(self):
        return _access.get_serving_groups(self)
    name = fields.Char('Name', required=True, copy=True)
    description = fields.Text('Description')
    res_name = fields.Char('Resource Name', compute='_compute_res_name')
    res_model = fields.Char('Resource Model')
    res_field = fields.Char('Resource Field')
    res_id = fields.Many2oneReference('Resource ID', model_field='res_model')
    company_id = fields.Many2one('res.company', string='Company', change_default=True,
                                 default=lambda self: self.env.company)
    type = fields.Selection([('url', 'URL'), ('binary', 'File')],
                            string='Type', required=True, default='binary', change_default=True,
                            help="You can either upload a file from your computer or copy/paste an internet link to your file.")
    url = fields.Char('Url', index='btree_not_null', size=1024)
    public = fields.Boolean('Is public document')
    res_access_read = fields.Boolean(
        groups=fields.NO_ACCESS,
        compute=lambda self: self._compute_res_access('read'),
        search=lambda self, operator, value: self._search_res_access('read', operator),
        compute_sudo=True, depends_context=('uid',))
    res_access_write = fields.Boolean(
        groups=fields.NO_ACCESS,
        compute=lambda self: self._compute_res_access('write'),
        search=lambda self, operator, value: self._search_res_access('write', operator),
        compute_sudo=True, depends_context=('uid',))
    access_token = fields.Char('Access Token', groups="base.group_user")
    raw = fields.Binary(string="File Content (raw)", compute='_compute_raw', inverse='_inverse_raw')
    db_datas = fields.Binary('Database Data', attachment=False)
    store_fname = fields.Char('Stored Filename', index=True)
    file_size = fields.Integer('File Size', readonly=True)
    checksum = fields.Char("Checksum/SHA1", size=40, readonly=True)
    mimetype = fields.Char('Mime Type', readonly=True)
    index_content = fields.Text('Indexed Content', readonly=True, prefetch=False)
    _res_idx = models.Index("(res_model, res_id)")
    def _check_serving_attachments(self):
        return _access._check_serving_attachments(self)
    @api.constrains('res_model', 'res_id')
    def _check_circular_attachment(self):
        return _access._check_circular_attachment(self)
    @api.model
    def check(self, mode, values=None):
        return _access.check(self, mode, values)
    def _make_access_error_message(self, operation, domain):
        return _access._make_access_error_message(self, operation, domain)
    def _compute_res_access(self, operation: str):
        return _access._compute_res_access(self, operation)
    def _search_res_access(self, operation, domain_operator):
        return _access._search_res_access(self, operation, domain_operator)
    def _inaccessible_comodel_records(self, model_and_ids: dict[str, Collection[int]], operation: str):
        return _access._inaccessible_comodel_records(self, model_and_ids, operation)
    @api.model
    def _search(self, domain, offset=0, limit=None, order=None, *, active_test=True, bypass_access=False):
        return _access._search(self, domain, offset, limit, order, active_test=active_test, bypass_access=bypass_access)
    def write(self, vals):
        return _records.write(self, vals)
    def copy_data(self, default=None):
        return _records.copy_data(self, default)
    def unlink(self):
        return _records.unlink(self)
    @api.model_create_multi
    def create(self, vals_list):
        return _records.create(self, vals_list)
    def _post_add_create(self, **kwargs):
        return _records._post_add_create(self, **kwargs)
    def generate_access_token(self):
        return _records.generate_access_token(self)
    def _get_raw_access_token(self):
        return _records._get_raw_access_token(self)
    @api.model
    def create_unique(self, vals_list):
        return _records.create_unique(self, vals_list)
    def _generate_access_token(self):
        return _records._generate_access_token(self)
    @api.model
    def action_get(self):
        return _records.action_get(self)
    @api.model
    def _get_serve_attachment(self, url, extra_domain=None, order=None):
        return _serving._get_serve_attachment(self, url, extra_domain, order)
    @api.model
    def regenerate_assets_bundles(self):
        return _serving.regenerate_assets_bundles(self)
    def _upload_file(self, file: io.IOBase, create_vals: api.ValuesType) -> typing.Self:
        return _content._upload_file(self, file, create_vals)
    def _to_http_stream(self):
        return _serving._to_http_stream(self)
    def _is_remote_source(self):
        return _serving._is_remote_source(self)
    def _can_return_content(self, field_name=None, access_token=None):
        return _serving._can_return_content(self, field_name, access_token)
    def _migrate_remote_to_local(self):
        return _serving._migrate_remote_to_local(self)


IrAttachment._inverse_raw.__override__ = False  # whitelist super()


# the delegated methods of the class, and the modules that use the class: at the end, they import this module
from . import storage as _storage, content as _content, access as _access, records as _records, serving as _serving  # noqa: E402
