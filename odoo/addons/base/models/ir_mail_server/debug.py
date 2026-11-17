# Part of Odoo. See LICENSE file for full copyright and licensing details.

import logging
import smtplib



_logger = logging.getLogger('odoo.addons.base.models.ir_mail_server')


# Python 3: patch SMTP's internal printer/debugger
def _print_debug(self, *args):
    _logger.debug(' '.join(str(a) for a in args))
smtplib.SMTP._print_debug = _print_debug

# Python 2: replace smtplib's stderr
class WriteToLogger(object):
    def write(self, s):
        _logger.debug(s)
smtplib.stderr = WriteToLogger()
