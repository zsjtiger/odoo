# Part of Odoo. See LICENSE file for full copyright and licensing details.
"""The choice of the outgoing server for a message: the from filters and the fallbacks."""

from odoo import _, fields
from odoo.exceptions import UserError
from odoo.tools import (
    email_domain_extract,
    email_domain_normalize,
    email_normalize,
)

from .server import _logger

def _check_forced_mail_server(self, mail_server, allow_archived, smtp_from):
    if not allow_archived and not mail_server.active:
        raise UserError(_('The server "%s" cannot be used because it is archived.', mail_server.display_name))


def _find_mail_server_allowed_domain(self):
    """Overridable domain getter for all mail servers that may be used as default."""
    return fields.Domain.TRUE


def _find_mail_server(self, email_from, mail_servers=None):
    """Find the appropriate mail server for the given email address.

        :rtype: tuple[IrMail_Server | None, str]
        :returns: A two-elements tuple: ``(Record<ir.mail_server>, email_from)``

          1. Mail server to use to send the email (``None`` if we use the command-line arguments)
          2. Email FROM to use to send the email (in some case, it might be impossible
             to use the given email address directly if no mail server is configured for)
        """
    email_from_normalized = email_normalize(email_from)
    email_from_domain = email_domain_extract(email_from_normalized)
    notifications_email = self.env.context.get('domain_notifications_email') or email_normalize(self._get_default_from_address())
    notifications_domain = email_domain_extract(notifications_email)

    if mail_servers is None:
        mail_servers = self.sudo().search(self._find_mail_server_allowed_domain(), order='sequence')
    # 0. Archived mail server should never be used
    mail_servers = mail_servers.filtered('active')

    def first_match(target, normalize_method):
        for mail_server in mail_servers:
            if mail_server.from_filter and any(
                normalize_method(email.strip()) == target
                for email in mail_server.from_filter.split(',')
            ):
                return mail_server

    # 1. Try to find a mail server for the right mail from
    # Skip if passed email_from is False (example Odoobot has no email address)
    if email_from_normalized:
        if mail_server := first_match(email_from_normalized, email_normalize):
            return mail_server, email_from

        if mail_server := first_match(email_from_domain, email_domain_normalize):
            return mail_server, email_from

    mail_servers = self._filter_mail_servers_fallback(mail_servers)

    # 2. Try to find a mail server for <notifications@domain.com>
    if notifications_email:
        if mail_server := first_match(notifications_email, email_normalize):
            return mail_server, notifications_email

        if mail_server := first_match(notifications_domain, email_domain_normalize):
            return mail_server, notifications_email

    # 3. Take the first mail server without "from_filter" because
    # nothing else has been found... Will spoof the FROM because
    # we have no other choices (will use the notification email if available
    # otherwise we will use the user email)
    if mail_server := mail_servers.filtered(lambda m: not m.from_filter):
        return mail_server[0], notifications_email or email_from

    # 4. Return the first mail server even if it was configured for another domain
    if mail_servers:
        _logger.warning(
            "No mail server matches the from_filter, using %s as fallback",
            notifications_email or email_from)
        return mail_servers[0], notifications_email or email_from

    # 5: SMTP config in command-line arguments
    from_filter = self.env['ir.mail_server']._get_default_from_filter()

    if self._match_from_filter(email_from, from_filter):
        return None, email_from

    if notifications_email and self._match_from_filter(notifications_email, from_filter):
        return None, notifications_email

    _logger.warning(
        "The from filter of the CLI configuration does not match the notification email "
        "or the user email, using %s as fallback",
        notifications_email or email_from)
    return None, notifications_email or email_from


def _filter_mail_servers_fallback(self, servers):
    """Filter the mail servers that can be used as fallback, or for default email from."""
    return servers


def _match_from_filter(self, email_from, from_filter):
    """Return True is the given email address match the "from_filter" field.

        The from filter can be Falsy (always match),
        a domain name or an full email address.
        """
    if not from_filter:
        return True

    normalized_mail_from = email_normalize(email_from)
    normalized_domain = email_domain_extract(normalized_mail_from)

    for email_filter in self._parse_from_filter(from_filter):
        if '@' in email_filter and email_normalize(email_filter) == normalized_mail_from:
            return True
        if '@' not in email_filter and email_domain_normalize(email_filter) == normalized_domain:
            return True
    return False


def _parse_from_filter(self, from_filter):
    return [part.strip() for part in (from_filter or '').split(',') if part.strip()]
