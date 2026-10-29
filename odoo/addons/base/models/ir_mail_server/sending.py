# Part of Odoo. See LICENSE file for full copyright and licensing details.
"""The sending of the messages: the entry point and the login."""

import smtplib
from odoo import _
from .errors import MailDeliveryException

from .server import _logger, _test_logger

def _smtp_login__(self, connection, smtp_user, smtp_password):  # noqa: PLW3201
    """Authenticate the SMTP connection.

        Can be overridden in other module for different authentication methods.Can be
        called on the model itself or on a singleton.

        :param connection: The SMTP connection to authenticate
        :param smtp_user: The user to used for the authentication
        :param smtp_password: The password to used for the authentication
        """
    connection.login(smtp_user, smtp_password)


def send_email(self, message, mail_server_id=None, smtp_server=None, smtp_port=None,
               smtp_user=None, smtp_password=None, smtp_encryption=None,
               smtp_ssl_certificate=None, smtp_ssl_private_key=None,
               smtp_debug=False, smtp_session=None):
    """Sends an email directly (no queuing).

        No retries are done, the caller should handle MailDeliveryException in order to ensure that
        the mail is never lost.

        If the mail_server_id is provided, sends using this mail server, ignoring other smtp_* arguments.
        If mail_server_id is None and smtp_server is None, use the default mail server (highest priority).
        If mail_server_id is None and smtp_server is not None, use the provided smtp_* arguments.
        If both mail_server_id and smtp_server are None, look for an 'smtp_server' value in server config,
        and fails if not found.

        :param message: the email.message.Message to send. The envelope sender will be extracted from the
                        ``Return-Path`` (if present), or will be set to the default bounce address.
                        The envelope recipients will be extracted from the combined list of ``To``,
                        ``CC`` and ``BCC`` headers.
        :param smtp_session: optional pre-established SMTP session. When provided,
                             overrides `mail_server_id` and all the `smtp_*` parameters.
                             Passing the matching `mail_server_id` may yield better debugging/log
                             messages. The caller is in charge of disconnecting the session.
        :param mail_server_id: optional id of ir.mail_server to use for sending. overrides other smtp_* arguments.
        :param smtp_server: optional hostname of SMTP server to use
        :param smtp_encryption: optional TLS mode, one of 'none', 'starttls', 'starttls_strict', 'ssl', or 'ssl_strict'.
            The 'strict' variants verify the remote server's certificate against the operating system trust store.
        :param smtp_port: optional SMTP port, if mail_server_id is not passed
        :param smtp_user: optional SMTP user, if mail_server_id is not passed
        :param smtp_password: optional SMTP password to use, if mail_server_id is not passed
        :param smtp_ssl_certificate: filename of the SSL certificate used for authentication
        :param smtp_ssl_private_key: filename of the SSL private key used for authentication
        :param smtp_debug: optional SMTP debug flag, if mail_server_id is not passed
        :return: the Message-ID of the message that was just sent, if successfully sent, otherwise raises
                 MailDeliveryException and logs root cause.
        """
    smtp = smtp_session
    if not smtp:
        smtp = self._connect__(
            smtp_server, smtp_port, smtp_user, smtp_password, smtp_encryption,
            smtp_from=message['From'], ssl_certificate=smtp_ssl_certificate, ssl_private_key=smtp_ssl_private_key,
            smtp_debug=smtp_debug, mail_server_id=mail_server_id,)

    smtp_from, smtp_to_list, message = self._prepare_email_message__(message, smtp)

    # Do not actually send emails in testing mode!
    if self._disable_send():
        _test_logger.debug("skip sending email in test mode")
        return message['Message-Id']

    try:
        message_id = message['Message-Id']

        smtp.send_message(message, smtp_from, smtp_to_list)

        # do not quit() a pre-established smtp_session
        if not smtp_session:
            smtp.quit()
    except smtplib.SMTPServerDisconnected:
        raise
    except Exception as e:
        msg = _(
            "Mail delivery failed via SMTP server '%(server)s'.\n%(exception_name)s: %(message)s",
            server=getattr(smtp, 'mail_server_name', smtp_server),
            exception_name=e.__class__.__name__,
            message=e,
        )
        _logger.info(msg)
        raise MailDeliveryException(_("Mail Delivery Failed"), msg)
    return message_id
