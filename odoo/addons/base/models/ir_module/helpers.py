# Part of Odoo. See LICENSE file for full copyright and licensing details.

import functools
import logging
import os
import shutil


from odoo.exceptions import AccessDenied
from odoo.http import request


_logger = logging.getLogger('odoo.addons.base.models.ir_module')


ACTION_DICT = {
    'view_mode': 'form',
    'res_model': 'base.module.upgrade',
    'target': 'new',
    'type': 'ir.actions.act_window',
}


def backup(path, raise_exception=True):
    path = os.path.normpath(path)
    if not os.path.exists(path):
        if not raise_exception:
            return None
        raise OSError('path does not exists')
    cnt = 1
    while True:
        bck = '%s~%d' % (path, cnt)
        if not os.path.exists(bck):
            shutil.move(path, bck)
            return bck
        cnt += 1


def assert_log_admin_access[T](method: T, /) -> T:
    """Decorator checking that the calling user is an administrator, and logging the call.

    Raises an AccessDenied error if the user does not have administrator privileges, according
    to `user._is_admin()`.
    """
    @functools.wraps(method)
    def check_and_log(self, *args, **kwargs):
        user = self.env.user
        origin = request.httprequest.remote_addr if request else 'n/a'
        log_data = (method.__name__, self.sudo().mapped('display_name'), user.login, user.id, origin)
        if not self.env.is_admin():
            _logger.warning('DENY access to module.%s on %s to user %s ID #%s via %s', *log_data)
            raise AccessDenied()
        _logger.info('ALLOW access to module.%s on %s to user %s #%s via %s', *log_data)
        return method(self, *args, **kwargs)
    return check_and_log


STATES = [
    ('uninstallable', 'Uninstallable'),
    ('uninstalled', 'Not Installed'),
    ('installed', 'Installed'),
    ('to upgrade', 'To be upgraded'),
    ('to remove', 'To be removed'),
    ('to install', 'To be installed'),
]


XML_DECLARATION = (
    '<?xml version='.encode('utf-8'),
    '<?xml version='.encode('utf-16-be'),
    '<?xml version='.encode('utf-16-le'),
)
