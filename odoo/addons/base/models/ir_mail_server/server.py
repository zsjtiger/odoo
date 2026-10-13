# Part of Odoo. See LICENSE file for full copyright and licensing details.
"""The outgoing mail servers (ir.mail_server): the model, its fields and the SMTP connection. The methods are split by concern in the other modules of this package."""

import functools
import logging
import smtplib
import ssl
import idna
from cryptography.hazmat.primitives.serialization import load_pem_private_key
from cryptography.x509 import load_pem_x509_certificate
from OpenSSL.crypto import Error as SSLCryptoError
from OpenSSL.SSL import VERIFY_FAIL_IF_NO_PEER_CERT, VERIFY_PEER
from OpenSSL.SSL import Error as SSLError
from urllib3.contrib.pyopenssl import PyOpenSSLContext
from odoo import _, api, fields, models, tools
from odoo.exceptions import UserError
from .tls import _verify_check_hostname_callback


class IrMail_Server(models.Model):
    """Represents an SMTP server, able to send outgoing emails, with SSL and TLS capabilities."""
    _name = 'ir.mail_server'
    _description = 'Mail Server'
    _order = 'sequence, id'
    _allow_sudo_commands = False
    NO_VALID_RECIPIENT = ("At least one valid recipient address should be "
                          "specified for outgoing emails (To/Cc/Bcc)")
    NO_FOUND_FROM = ("You must either provide a sender address explicitly or configure "
          "using the combination of `mail.catchall.domain` and `mail.default.from` "
          "ICPs, in the server configuration file or with the --email-from startup "
          "parameter.")
    NO_FOUND_SMTP_FROM = "The Return-Path or From header is required for any outbound email"
    NO_VALID_FROM = "Malformed 'Return-Path' or 'From' address. It should contain one valid plain ASCII email"
    name = fields.Char(string='Name', required=True, index=True)
    from_filter = fields.Char(
        "FROM Filtering",
        help='Comma-separated list of addresses or domains for which this server can be used.\n'
             'e.g.: "notification@odoo.com" or "odoo.com"')
    smtp_host = fields.Char(string='SMTP Server', help="Hostname or IP of SMTP server")
    smtp_port = fields.Integer(string='SMTP Port', default=25, help="SMTP Port. Usually 465 for SSL, and 25 or 587 for other cases.")
    smtp_authentication = fields.Selection([
        ('login', 'Username'),
        ('certificate', 'SSL Certificate'),
        ('cli', 'Command Line Interface')
    ], string='Authenticate with', required=True, default='login')
    smtp_authentication_info = fields.Text('Authentication Info', compute='_compute_smtp_authentication_info')
    smtp_user = fields.Char(string='Username', help="Optional username for SMTP authentication", groups='base.group_system')
    smtp_pass = fields.Char(string='Password', help="Optional password for SMTP authentication", groups='base.group_system')
    smtp_encryption = fields.Selection([('none', 'None'),
                                        ('starttls_strict', 'TLS (STARTTLS), encryption and validation'),
                                        ('starttls', 'TLS (STARTTLS), encryption only'),
                                        ('ssl_strict', 'SSL/TLS, encryption and validation'),
                                        ('ssl', 'SSL/TLS, encryption only')],
                                       string='Connection Encryption', required=True, default='none',
                                       help="Choose the connection encryption scheme:\n"
                                            "- None: SMTP sessions are done in cleartext.\n"
                                            "- TLS (STARTTLS): TLS encryption is requested at start of SMTP session (Recommended)\n"
                                            "- SSL/TLS: SMTP sessions are encrypted with SSL/TLS through a dedicated port (default: 465)\n"
                                            "\n"
                                            "Choose an additionnal variant for SSL or TLS:\n"
                                            "- encryption and validation: encrypt the data and authentify the server using its SSL certificate (Recommended)\n"
                                            "- encryption only: encrypt the data but skip server authentication")
    smtp_ssl_certificate = fields.Binary(
        'SSL Certificate', groups='base.group_system', attachment=False,
        help='SSL certificate used for authentication')
    smtp_ssl_private_key = fields.Binary(
        'SSL Private Key', groups='base.group_system', attachment=False,
        help='SSL private key used for authentication')
    smtp_debug = fields.Boolean(string='Debugging', help="If enabled, the full output of SMTP sessions will "
                                                         "be written to the server log at DEBUG level "
                                                         "(this is very verbose and may include confidential info!)")
    sequence = fields.Integer(string='Priority', default=10, help="When no specific mail server is requested for a mail, the highest priority one "
                                                                  "is used. Default priority is 10 (smaller number = higher priority)")
    active = fields.Boolean(default=True)
    _certificate_requires_tls = models.Constraint(
        "CHECK(smtp_encryption != 'none' OR smtp_authentication != 'certificate')",
        "Certificate-based authentication requires a TLS transport",
    )
    @api.depends('smtp_authentication')
    def _compute_smtp_authentication_info(self):
        return _settings._compute_smtp_authentication_info(self)
    @api.constrains('smtp_authentication', 'smtp_ssl_certificate', 'smtp_ssl_private_key')
    def _check_smtp_ssl_files(self):
        return _settings._check_smtp_ssl_files(self)
    def write(self, vals):
        return _settings.write(self, vals)
    def _active_usages_compute(self):
        return _settings._active_usages_compute(self)
    @api.model
    def _get_max_email_size(self):
        return _settings._get_max_email_size(self)
    def _get_test_email_from(self):
        return _settings._get_test_email_from(self)
    def _get_test_email_to(self):
        return _settings._get_test_email_to(self)
    def test_smtp_connection(self):
        return _settings.test_smtp_connection(self)
    @classmethod
    def _disable_send(cls):
        return _settings._disable_send(cls)
    def _connect__(self, host=None, port=None, user=None, password=None, encryption=None,  # noqa: PLW3201
                smtp_from=None, ssl_certificate=None, ssl_private_key=None, smtp_debug=False, mail_server_id=None,
                allow_archived=False):
        """Returns a new SMTP connection to the given SMTP server.
           When running in test mode, this method does nothing and returns `None`.

           :param host: host or IP of SMTP server to connect to, if mail_server_id not passed
           :param int port: SMTP port to connect to
           :param user: optional username to authenticate with
           :param password: optional password to authenticate with
           :param str encryption: optional, ``'none'`` | ``'ssl'`` | ``'ssl_strict'`` | ``'starttls'`` | ``'starttls_strict'``.
               The 'strict' variants verify the remote server's certificate against the operating system trust store.
           :param smtp_from: FROM SMTP envelop, used to find the best mail server
           :param ssl_certificate: filename of the SSL certificate used for authentication
               Used when no mail server is given and overwrite  the command-line argument "smtp_ssl_certificate"
           :param ssl_private_key: filename of the SSL private key used for authentication
               Used when no mail server is given and overwrite  the command-line argument "smtp_ssl_private_key"
           :param bool smtp_debug: toggle debugging of SMTP sessions (all i/o
                              will be output in logs)
           :param mail_server_id: ID of specific mail server to use (overrides other parameters)
           :param bool allow_archived: by default (False), an exception is raised when calling this method on an
               archived record (using mail_server_id param). It can be set to True for testing so that the exception is
               no longer raised.
        """
        # Do not actually connect while running in test mode
        if self._disable_send():
            return None
        mail_server = smtp_encryption = None
        if mail_server_id:
            mail_server = self.sudo().browse(mail_server_id)
            self._check_forced_mail_server(mail_server, allow_archived, smtp_from)

        elif not host:
            mail_server, smtp_from = self.sudo()._find_mail_server(smtp_from)

        if not mail_server:
            mail_server = self.env['ir.mail_server']
        ssl_context = None

        if mail_server and mail_server.smtp_authentication != "cli":
            smtp_server = mail_server.smtp_host
            smtp_port = mail_server.smtp_port
            if mail_server.smtp_authentication == "certificate":
                smtp_user = None
                smtp_password = None
            else:
                smtp_user = mail_server.smtp_user
                smtp_password = mail_server.smtp_pass
            smtp_encryption = mail_server.smtp_encryption
            smtp_debug = smtp_debug or mail_server.smtp_debug
            from_filter = mail_server.from_filter

            if mail_server.smtp_authentication == "certificate":
                try:
                    ssl_context = PyOpenSSLContext(ssl.PROTOCOL_TLS)
                    if mail_server.smtp_encryption in ('ssl_strict', 'starttls_strict'):
                        ssl_context.set_default_verify_paths()
                        ssl_context._ctx.set_verify(
                            VERIFY_PEER | VERIFY_FAIL_IF_NO_PEER_CERT,
                            functools.partial(_verify_check_hostname_callback, hostname=smtp_server)
                        )
                    else:  # ssl, starttls
                        ssl_context.verify_mode = ssl.CERT_NONE
                    ssl_context._ctx.use_certificate(load_pem_x509_certificate(
                        mail_server.smtp_ssl_certificate.content))
                    ssl_context._ctx.use_privatekey(load_pem_private_key(
                        mail_server.smtp_ssl_private_key.content,
                        password=None))
                    # Check that the private key match the certificate
                    ssl_context._ctx.check_privatekey()
                except SSLCryptoError as e:
                    raise UserError(_('The private key or the certificate is not a valid file. \n%s', str(e)))
                except SSLError as e:
                    raise UserError(_('Could not load your certificate / private key. \n%s', str(e)))
            elif mail_server.smtp_encryption != 'none':
                if mail_server.smtp_encryption in ('ssl_strict', 'starttls_strict'):
                    ssl_context = ssl.create_default_context()
                    ssl_context.check_hostname = True
                    ssl_context.verify_mode = ssl.CERT_REQUIRED
                else:  # ssl, starttls
                    ssl_context = ssl.create_default_context()
                    ssl_context.check_hostname = False
                    ssl_context.verify_mode = ssl.CERT_NONE

        else:
            # we were passed individual smtp parameters or nothing and there is no default server
            smtp_server = host or tools.config.get('smtp_server')
            smtp_port = tools.config.get('smtp_port', 25) if port is None else port
            smtp_user = user or tools.config.get('smtp_user')
            smtp_password = password or tools.config.get('smtp_password')
            if mail_server:
                from_filter = mail_server.from_filter
            else:
                from_filter = self.env['ir.mail_server']._get_default_from_filter()

            smtp_encryption = encryption
            if smtp_encryption is None and tools.config.get('smtp_ssl'):
                smtp_encryption = 'starttls' # smtp_ssl => STARTTLS as of v7
            smtp_ssl_certificate_filename = ssl_certificate or tools.config.get('smtp_ssl_certificate_filename')
            smtp_ssl_private_key_filename = ssl_private_key or tools.config.get('smtp_ssl_private_key_filename')

            if smtp_ssl_certificate_filename and smtp_ssl_private_key_filename:
                try:
                    ssl_context = PyOpenSSLContext(ssl.PROTOCOL_TLS)
                    ssl_context.verify_mode = ssl.CERT_NONE
                    ssl_context.load_cert_chain(smtp_ssl_certificate_filename, keyfile=smtp_ssl_private_key_filename)
                    # Check that the private key match the certificate
                    ssl_context._ctx.check_privatekey()
                except SSLCryptoError as e:
                    raise UserError(_('The private key or the certificate is not a valid file. \n%s', str(e)))
                except SSLError as e:
                    raise UserError(_('Could not load your certificate / private key. \n%s', str(e)))

        if not smtp_server:
            raise UserError(_(
                "Missing SMTP Server\n"
                "Please define at least one SMTP server, "
                "or provide the SMTP parameters explicitly.",
            ))

        if smtp_encryption in ('ssl', 'ssl_strict'):
            connection = smtplib.SMTP_SSL(smtp_server, smtp_port, timeout=SMTP_TIMEOUT, context=ssl_context)
        else:
            connection = smtplib.SMTP(smtp_server, smtp_port, timeout=SMTP_TIMEOUT)
        connection.set_debuglevel(smtp_debug)
        if smtp_encryption in ('starttls', 'starttls_strict'):
            # starttls() will perform ehlo() if needed first
            # and will discard the previous list of services
            # after successfully performing STARTTLS command,
            # (as per RFC 3207) so for example any AUTH
            # capability that appears only on encrypted channels
            # will be correctly detected for next step
            connection.starttls(context=ssl_context)

        if smtp_user:
            # Attempt authentication - will raise if AUTH service not supported
            local, at, domain = smtp_user.rpartition('@')
            if at:
                smtp_user = local + at + idna.encode(domain).decode('ascii')
            mail_server._smtp_login__(connection, smtp_user, smtp_password or '')

        # Some methods of SMTP don't check whether EHLO/HELO was sent.
        # Anyway, as it may have been sent by login(), all subsequent usages should consider this command as sent.
        connection.ehlo_or_helo_if_needed()

        # Store the "from_filter" of the mail server / command-line argument to  know if we
        # need to change the FROM headers or not when we will prepare the mail message
        connection.from_filter = from_filter
        connection.smtp_from = smtp_from
        connection.mail_server_name = mail_server.display_name if mail_server else smtp_server

        return connection
    def _check_forced_mail_server(self, mail_server, allow_archived, smtp_from):
        return _selection._check_forced_mail_server(self, mail_server, allow_archived, smtp_from)
    def _smtp_login__(self, connection, smtp_user, smtp_password):
        return _sending._smtp_login__(self, connection, smtp_user, smtp_password)
    def _build_email__(self, email_from, email_to, subject, body, email_cc=None, email_bcc=None, reply_to=False, attachments=None, message_id=None, references=None, object_id=False, subtype='plain', headers=None, body_alternative=None, subtype_alternative='plain'):
        return _message._build_email__(self, email_from, email_to, subject, body, email_cc, email_bcc, reply_to, attachments, message_id, references, object_id, subtype, headers, body_alternative, subtype_alternative)
    @api.model
    def _get_default_bounce_address(self):
        return _message._get_default_bounce_address(self)
    @api.model
    def _get_default_from_address(self):
        return _message._get_default_from_address(self)
    @api.model
    def _get_default_from_filter(self):
        return _message._get_default_from_filter(self)
    def _prepare_email_message__(self, message, smtp_session):
        return _message._prepare_email_message__(self, message, smtp_session)
    @api.model
    def _alter_message__(self, message, smtp_from, smtp_to_list):
        return _message._alter_message__(self, message, smtp_from, smtp_to_list)
    @api.model
    def _prepare_smtp_to_list(self, message, smtp_session):
        return _message._prepare_smtp_to_list(self, message, smtp_session)
    @api.model
    def send_email(self, message, mail_server_id=None, smtp_server=None, smtp_port=None, smtp_user=None, smtp_password=None, smtp_encryption=None, smtp_ssl_certificate=None, smtp_ssl_private_key=None, smtp_debug=False, smtp_session=None):
        return _sending.send_email(self, message, mail_server_id, smtp_server, smtp_port, smtp_user, smtp_password, smtp_encryption, smtp_ssl_certificate, smtp_ssl_private_key, smtp_debug, smtp_session)
    def _find_mail_server_allowed_domain(self):
        return _selection._find_mail_server_allowed_domain(self)
    def _find_mail_server(self, email_from, mail_servers=None):
        return _selection._find_mail_server(self, email_from, mail_servers)
    @api.model
    def _filter_mail_servers_fallback(self, servers):
        return _selection._filter_mail_servers_fallback(self, servers)
    @api.model
    def _match_from_filter(self, email_from, from_filter):
        return _selection._match_from_filter(self, email_from, from_filter)
    @api.model
    def _parse_from_filter(self, from_filter):
        return _selection._parse_from_filter(self, from_filter)
    @api.onchange('smtp_encryption')
    def _onchange_encryption(self):
        return _settings._onchange_encryption(self)


_logger = logging.getLogger('odoo.addons.base.models.ir_mail_server')




_test_logger = logging.getLogger('odoo.tests')


SMTP_TIMEOUT = 60


# the delegated methods of the class, and the modules that use the class: at the end, they import this module
from . import settings as _settings, message as _message, selection as _selection, sending as _sending  # noqa: E402
