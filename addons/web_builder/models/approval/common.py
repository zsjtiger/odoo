# Part of Odoo. See LICENSE file for full copyright and licensing details.
import logging

_logger = logging.getLogger(__name__)

# A reference to be able to securely pass
# info into a callstack via context.
_APPROVAL_SYMBOL_ = object()
