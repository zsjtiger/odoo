# Part of Odoo. See LICENSE file for full copyright and licensing details.
"""The serving of the attachments over HTTP: the streams, the served attachments and the remote sources."""

from __future__ import annotations

import os
import typing
from odoo import _, api
from odoo.exceptions import AccessError, ValidationError
from odoo.http.stream import Stream
from odoo.tools import consteq

if typing.TYPE_CHECKING:
    pass

from .attachment import IrAttachment

def _get_serve_attachment(self, url, extra_domain=None, order=None):
    domain = [('type', '=', 'binary'), ('url', '=', url)] + (extra_domain or [])
    return self.search(domain, order=order, limit=1)


def regenerate_assets_bundles(self):
    self.search([
        ('public', '=', True),
        ("url", "=like", "/web/assets/%"),
        ('res_model', '=', 'ir.ui.view'),
        ('res_id', '=', 0),
        ('create_uid', '=', api.SUPERUSER_ID),
    ]).unlink()
    self.env.transaction.invalidate_ormcache('assets')


def _to_http_stream(self):
    """ Create a :class:`~Stream`: from an ir.attachment record. """
    self.ensure_one()

    kw = dict(
        mimetype=self.mimetype,
        download_name=self.name,
        etag=self.checksum,
        public=self.public,
    )

    if self.store_fname and (path := self._full_path(self.store_fname)):
        # Try to read directly from the file system without reading the file
        try:
            stat = os.stat(path)
            return Stream(
                **kw,
                type='path',
                path=path,
                last_modified=stat.st_mtime,
                size=stat.st_size,
            )
        except OSError:
            pass

    elif self.url:
        return Stream(type='url', url=self.url, **kw)

    data = self.raw.content
    return Stream(
        type='data',
        data=data,
        last_modified=self.write_date,
        size=len(data),
        **kw,
    )


def _is_remote_source(self):
    self.ensure_one()
    return self.url and not self.file_size and self.url.startswith(('http://', 'https://', 'ftp://'))


def _can_return_content(self, field_name=None, access_token=None):
    attachment_sudo = self.sudo().with_context(prefetch_fields=False)
    if access_token:
        if not consteq(attachment_sudo.access_token or "", access_token):
            raise AccessError("Invalid access token")  # pylint: disable=missing-gettext
        return True
    if attachment_sudo.public:
        return True
    if self.env.user._is_portal():
        # Check the read access on the record linked to the attachment
        # eg: Allow to download an attachment on a task from /my/tasks/task_id
        self.check_access('read')
        return True
    return super(IrAttachment, self)._can_return_content(field_name, access_token)


def _migrate_remote_to_local(self):
    if self.type == 'binary':
        return
    if self.type == 'url':
        raise ValidationError(_("URL attachment (%s) shouldn't be migrated to local.", self.id))
