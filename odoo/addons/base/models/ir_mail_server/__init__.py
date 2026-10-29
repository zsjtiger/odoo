# Part of Odoo. See LICENSE file for full copyright and licensing details.
# ruff: noqa: F401
"""The outgoing mail servers: the model, the addresses, the TLS checks, the mail policy and the SMTP debugging. The names are re-exported here."""

# the helpers first; the debug and policy modules patch smtplib and email when they are imported, so they come before the model
from .errors import MailDeliveryException
from .addresses import address_pattern, extract_rfc2822_addresses, is_ascii
from .tls import _verify_check_hostname_callback
from .debug import WriteToLogger, _print_debug
from .policy import (
    IdentificationFieldsNoFoldPolicy,
    RFC5322_IDENTIFICATION_HEADERS,
    USER_DEFINED_HEADERS,
    _maxFoldPolicy,
    _noFoldPolicy,
)
from .server import IrMail_Server, SMTP_TIMEOUT
