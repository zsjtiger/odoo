# Part of Odoo. See LICENSE file for full copyright and licensing details.
"""The records of the attachments: their writes, copies, deletions and creations, and their access tokens."""

from __future__ import annotations

import typing
import uuid
from collections import defaultdict
from odoo import _
from odoo.exceptions import AccessError, UserError
from odoo.tools import OrderedSet
from odoo.tools.misc import limited_field_access_token
from .helpers import (
    CREATE_FROM_STREAM_FLAG,
)

if typing.TYPE_CHECKING:
    pass

from .attachment import IrAttachment

def write(self, vals):
    self.check_access('write')
    if vals.get('res_model') or vals.get('res_id'):
        model_and_ids = defaultdict(OrderedSet)
        if 'res_model' in vals and 'res_id' in vals:
            model_and_ids[vals['res_model']].add(vals['res_id'])
        else:
            for record in self:
                model_and_ids[vals.get('res_model', record.res_model)].add(vals.get('res_id', record.res_id))
        if any(self._inaccessible_comodel_records(model_and_ids, 'write')):
            raise AccessError(_("Sorry, you are not allowed to access this document."))
    # remove computed field depending of raw
    for field in ('file_size', 'checksum', 'store_fname'):
        vals.pop(field, False)
    if 'mimetype' in vals or 'raw' in vals:
        vals = self._check_contents(vals)
    res = super(IrAttachment, self).write(vals)
    if 'url' in vals or 'type' in vals:
        self._check_serving_attachments()
    return res


def copy_data(self, default=None):
    default = dict(default or {})
    vals_list = super(IrAttachment, self).copy_data(default=default)
    for attachment, vals in zip(self, vals_list):
        if not default.keys() & {'db_datas', 'raw'}:
            # ensure the content is kept and recomputes checksum/store_fname
            vals['raw'] = attachment.raw
    return vals_list


def unlink(self):
    # First delete in the database, *then* in the filesystem if the
    # database allowed it. Helps avoid errors when concurrent transactions
    # are deleting the same file, and some of the transactions are
    # rolled back by PostgreSQL (due to concurrent updates detection).
    to_delete = OrderedSet(attach.store_fname for attach in self if attach.store_fname)
    res = super(IrAttachment, self).unlink()
    for file_path in to_delete:
        self._file_delete(file_path)

    return res


def create(self, vals_list):
    record_tuple_set = set()

    if self.env.context.get('ir_attachment_from_stream') is not CREATE_FROM_STREAM_FLAG:
        # remove computed field depending of raw
        vals_list = [{
            key: value
            for key, value
            in vals.items()
            if key not in ('file_size', 'checksum', 'store_fname')
        } for vals in vals_list]
    raw_map = {}

    for values in vals_list:
        values = self._check_contents(values)
        if raw := values.pop('raw', None):
            values.update(self._get_datas_related_values(raw, values['mimetype']))
            if fname := values.get('store_fname'):
                raw_map[fname] = raw

        # 'check()' only uses res_model and res_id from values, and make an exists.
        # We can group the values by model, res_id to make only one query when
        # creating multiple attachments on a single record.
        record_tuple = (values.get('res_model'), values.get('res_id'))
        record_tuple_set.add(record_tuple)

    # don't use possible contextual recordset for check, see commit for details
    model_and_ids = defaultdict(set)
    for res_model, res_id in record_tuple_set:
        model_and_ids[res_model].add(res_id)
    if any(self._inaccessible_comodel_records(model_and_ids, 'write')):
        raise AccessError(_("Sorry, you are not allowed to access this document."))
    records = super(IrAttachment, self).create(vals_list)
    for fname, raw in raw_map.items():
        with raw.open() as f:
            self._file_write(fname, f)
    records._check_serving_attachments()
    return records


def _post_add_create(self, **kwargs):
    # TODO master: rename to _post_upload, better indicating its usage
    pass


def generate_access_token(self):
    tokens = []
    for attachment in self:
        if attachment.access_token:
            tokens.append(attachment.access_token)
            continue
        access_token = self._generate_access_token()
        attachment.write({'access_token': access_token})
        tokens.append(access_token)
    return tokens


def _get_raw_access_token(self):
    """Return a scoped access token for the `raw` field. The token can be
        used with `ir_binary._find_record` to bypass access rights.

        :rtype: str
        """
    self.ensure_one()
    return limited_field_access_token(self, "raw", scope="binary")


def create_unique(self, vals_list):
    result = self.browse()
    for vals in vals_list:
        try:
            vals = self._check_contents(vals)
        except ValueError:
            raise UserError(_("Attachment is not encoded in base64."))
        checksum = self._compute_checksum(vals['raw'] or b'')
        # Create only if record does not already exist for checksum and mimetype
        result += self.sudo().search([
            ['id', '!=', False],  # No implicit condition on res_field.
            ['checksum', '=', checksum],
            ['mimetype', '=', vals['mimetype']],
        ], limit=1) or self.create(vals)
    return result


def _generate_access_token(self):
    return str(uuid.uuid4())


def action_get(self):
    return self.env['ir.actions.act_window']._for_xml_id('base.action_attachment')
