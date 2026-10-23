# Part of Odoo. See LICENSE file for full copyright and licensing details.
"""The settings of the outgoing servers: the authentication and the certificates checks, the writes, the test emails and the connection test."""

import smtplib
import ssl
from socket import gaierror, timeout
import idna
from OpenSSL.SSL import Error as SSLError
from odoo import _, modules
from odoo.exceptions import UserError

from .server import IrMail_Server, _logger

try:
    # urllib3 1.26 (ubuntu jammy and up, debian bullseye and up)
    from urllib3.util.ssl_match_hostname import CertificateError
except ImportError:
    # urllib3 1.25 and below
    from urllib3.packages.ssl_match_hostname import CertificateError


def _compute_smtp_authentication_info(self):
    for server in self:
        if server.smtp_authentication == 'login':
            server.smtp_authentication_info = _(
                'Connect to your server through your usual username and password. \n'
                'This is the most basic SMTP authentication process and '
                'may not be accepted by all providers. \n')
        elif server.smtp_authentication == 'certificate':
            server.smtp_authentication_info = _(
                'Authenticate by using SSL certificates, belonging to your domain name. \n'
                'SSL certificates allow you to authenticate your mail server for the entire domain name.')
        elif server.smtp_authentication == 'cli':
            server.smtp_authentication_info = _(
                'Use the SMTP configuration set in the "Command Line Interface" arguments.')
        else:
            server.smtp_authentication_info = False


def _check_smtp_ssl_files(self):
    for mail_server in self:
        if mail_server.smtp_authentication == 'certificate':
            if not mail_server.smtp_ssl_private_key:
                raise UserError(_('SSL private key is missing for %s.', mail_server.name))
            if not mail_server.smtp_ssl_certificate:
                raise UserError(_('SSL certificate is missing for %s.', mail_server.name))


def write(self, vals):
    """Ensure we cannot archive a server in-use"""
    usages_per_server = {}
    if not vals.get('active', True):
        usages_per_server = self._active_usages_compute()

    if not usages_per_server:
        return super(IrMail_Server, self).write(vals)

    # Write cannot be performed as some server are used, build detailed usage per server
    usage_details_per_server = {}
    is_multiple_server_usage = len(usages_per_server) > 1
    for server in self:
        if server.id not in usages_per_server:
            continue
        usage_details = []
        if is_multiple_server_usage:
            usage_details.append(_('%s (Dedicated Outgoing Mail Server):', server.display_name))
        usage_details.extend(map(lambda u: f'- {u}', usages_per_server[server.id]))
        usage_details_per_server[server] = usage_details

    # Raise the error with the ordered list of servers and concatenated detailed usages
    servers_ordered_by_name = sorted(usage_details_per_server.keys(), key=lambda r: r.display_name)
    error_server_usage = ', '.join(server.display_name for server in servers_ordered_by_name)
    error_usage_details = '\n'.join(line
                                    for server in servers_ordered_by_name
                                    for line in usage_details_per_server[server])
    if is_multiple_server_usage:
        raise UserError(
            _('You cannot archive these Outgoing Mail Servers (%(server_usage)s) because they are still used in the following case(s):\n%(usage_details)s',
              server_usage=error_server_usage, usage_details=error_usage_details))
    raise UserError(
        _('You cannot archive this Outgoing Mail Server (%(server_usage)s) because it is still used in the following case(s):\n%(usage_details)s',
          server_usage=error_server_usage, usage_details=error_usage_details))


def _active_usages_compute(self):
    """Compute a dict server id to list of user-friendly outgoing mail servers usage of this record set.

        This method must be overridden by all modules that uses this class in order to complete the list with
        user-friendly string describing the active elements that could send mail through the instance of this class.
        :return dict: { ir_mail_server.id: usage_str_list }.
        """
    return dict()


def _get_max_email_size(self):
    return self.env['ir.config_parameter'].sudo().get_float('base.default_max_email_size', 20)


def _get_test_email_from(self):
    self.ensure_one()
    email_from = False
    if from_filter_parts := self._parse_from_filter(self.from_filter):
        # find first found complete email in filter parts
        email_from = next((email for email in from_filter_parts if "@" in email), False)
        # no complete email -> consider noreply
        if not email_from:
            email_from = f"noreply@{from_filter_parts[0]}"
    if not email_from:
        # Fallback to current user email if there's no from filter
        email_from = self.env.user.email
    if not email_from or "@" not in email_from:
        raise UserError(_('Please configure an email on the current user to simulate '
                          'sending an email message via this outgoing server'))
    return email_from


def _get_test_email_to(self):
    return "noreply@odoo.com"


def test_smtp_connection(self):
    """Test the connection.

        :return: client action to notify the user of the result of the operation
        :rtype: dict

        :raises UserError: if the connection fails
        """
    for server in self:
        smtp = False
        try:
            # simulate sending an email from current user's address - without sending it!
            email_from = server._get_test_email_from()
            email_to = server._get_test_email_to()
            smtp = self._connect__(mail_server_id=server.id, allow_archived=True, smtp_from=email_from)
            # Testing the MAIL FROM step should detect sender filter problems
            (code, repl) = smtp.mail(email_from)
            if code != 250:
                raise UserError(_('The server refused the sender address (%(email_from)s) with error %(repl)s', email_from=email_from, repl=repl))  # noqa: TRY301
            # Testing the RCPT TO step should detect most relaying problems
            (code, repl) = smtp.rcpt(email_to)
            if code not in (250, 251):
                raise UserError(_('The server refused the test recipient (%(email_to)s) with error %(repl)s', email_to=email_to, repl=repl))  # noqa: TRY301
            # Beginning the DATA step should detect some deferred rejections
            # Can't use self.data() as it would actually send the mail!
            smtp.putcmd("data")
            (code, repl) = smtp.getreply()
            if code != 354:
                raise UserError(_('The server refused the test connection with error %(repl)s', repl=repl))  # noqa: TRY301
        except (UnicodeError, idna.core.InvalidCodepoint) as e:
            raise UserError(_("Invalid server name!\n %s", e)) from e
        except (gaierror, timeout) as e:
            raise UserError(_("No response received. Check server address and port number.\n %s", e)) from e
        except smtplib.SMTPServerDisconnected as e:
            raise UserError(_("The server has closed the connection unexpectedly. Check configuration served on this port number.\n %s", e)) from e
        except smtplib.SMTPResponseException as e:
            raise UserError(_("Server replied with following exception:\n %s", e)) from e
        except smtplib.SMTPNotSupportedError as e:
            raise UserError(_("An option is not supported by the server:\n %s", e)) from e
        except smtplib.SMTPException as e:
            raise UserError(_("An SMTP exception occurred. Check port number and connection security type.\n %s", e)) from e
        except CertificateError as e:
            raise UserError(_("An SSL exception occurred. Check connection security type.\n CertificateError: %s", e)) from e
        except (ssl.SSLError, SSLError) as e:
            raise UserError(_("An SSL exception occurred. Check connection security type.\n %s", e)) from e
        except UserError:
            raise
        except Exception as e:
            _logger.warning("Connection test on %s failed with a generic error.", server, exc_info=True)
            raise UserError(_("Connection Test Failed! Here is what we got instead:\n %s", e)) from e
        finally:
            try:
                if smtp:
                    smtp.close()
            except Exception:
                # ignored, just a consequence of the previous exception
                pass
    return {
        'type': 'ir.actions.client',
        'tag': 'display_notification',
        'params': {
            'message': _('Connection Test Successful!'),
            'type': 'success',
            'sticky': False,
            'next': {'type': 'ir.actions.act_window_close'},  # force a form reload
        },
    }


def _disable_send(cls):
    """Whether to disable sending e-mails"""
    # no e-mails during testing or when registry is initializing
    return modules.module.current_test or not cls.pool.ready


def _onchange_encryption(self):
    result = {}
    if self.smtp_encryption == 'ssl':
        self.smtp_port = 465
        if not 'SMTP_SSL' in smtplib.__all__:
            result['warning'] = {
                'title': _('Warning'),
                'message': _('Your server does not seem to support SSL, you may want to try STARTTLS instead'),
            }
    else:
        self.smtp_port = 25
    return result
