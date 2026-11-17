# Part of Odoo. See LICENSE file for full copyright and licensing details.
"""The messages sent by the outgoing servers: the building, the preparation and the recipients."""

import datetime
import email.policy
from email.message import EmailMessage
from email.parser import BytesParser
from email.utils import make_msgid
from odoo import tools
from odoo.tools import (
    BinaryValue,
    email_normalize,
    encapsulate_email,
)
from .addresses import extract_rfc2822_addresses


def _build_email__(self, email_from, email_to, subject, body, email_cc=None, email_bcc=None, reply_to=False,  # noqa: PLW3201
                attachments=None, message_id=None, references=None, object_id=False, subtype='plain', headers=None,
                body_alternative=None, subtype_alternative='plain'):
    """Constructs an RFC2822 email.message.Message object based on the keyword arguments passed, and returns it.

           :param string email_from: sender email address
           :param list email_to: list of recipient addresses (to be joined with commas)
           :param string subject: email subject (no pre-encoding/quoting necessary)
           :param string body: email body, of the type ``subtype`` (by default, plaintext).
                               If html subtype is used, the message will be automatically converted
                               to plaintext and wrapped in multipart/alternative, unless an explicit
                               ``body_alternative`` version is passed.
           :param string body_alternative: optional alternative body, of the type specified in ``subtype_alternative``
           :param string reply_to: optional value of Reply-To header
           :param string object_id: optional tracking identifier, to be included in the message-id for
                                    recognizing replies. Suggested format for object-id is "res_id-model",
                                    e.g. "12345-crm.lead".
           :param string subtype: optional mime subtype for the text body (usually 'plain' or 'html'),
                                  must match the format of the ``body`` parameter. Default is 'plain',
                                  making the content part of the mail "text/plain".
           :param string subtype_alternative: optional mime subtype of ``body_alternative`` (usually 'plain'
                                              or 'html'). Default is 'plain'.
           :param list attachments: list of (filename, filecontents, mime) tuples, where filecontents are
                                    raw bytes or a binary value
           :param message_id:
           :param references:
           :param list email_cc: optional list of string values for CC header (to be joined with commas)
           :param list email_bcc: optional list of string values for BCC header (to be joined with commas)
           :param dict headers: optional map of headers to set on the outgoing mail (may override the
                                other headers, including Subject, Reply-To, Message-Id, etc.)
           :rtype: email.message.EmailMessage
           :return: the new RFC2822 email message
        """
    email_from = email_from or self.env.context.get('domain_notifications_email') or self._get_default_from_address()
    assert email_from, self.NO_FOUND_FROM

    headers = headers or {}         # need valid dict later
    email_cc = email_cc or []
    email_bcc = email_bcc or []

    msg = EmailMessage(policy=email.policy.SMTP)
    if not message_id:
        if object_id:
            message_id = tools.mail.generate_tracking_message_id(object_id)
        else:
            message_id = make_msgid()
    msg['Message-Id'] = message_id
    if references:
        msg['references'] = references
    msg['Subject'] = subject
    msg['From'] = email_from
    del msg['Reply-To']
    msg['Reply-To'] = reply_to or email_from
    msg['To'] = email_to
    if email_cc:
        msg['Cc'] = email_cc
    if email_bcc:
        msg['Bcc'] = email_bcc
    msg['Date'] = datetime.datetime.utcnow()
    for key, value in headers.items():
        msg[key] = value

    email_body = body or ''
    if subtype == 'html' and not body_alternative:
        msg['MIME-Version'] = '1.0'
        msg.add_alternative(tools.html2plaintext(email_body), subtype='plain', charset='utf-8')
        msg.add_alternative(email_body, subtype=subtype, charset='utf-8')
    elif body_alternative:
        msg['MIME-Version'] = '1.0'
        msg.add_alternative(body_alternative, subtype=subtype_alternative, charset='utf-8')
        msg.add_alternative(email_body, subtype=subtype, charset='utf-8')
    else:
        msg.set_content(email_body, subtype=subtype, charset='utf-8')

    if attachments:
        for (fname, fcontent, mime) in attachments:
            maintype, subtype = mime.split('/') if mime and '/' in mime else ('application', 'octet-stream')
            if isinstance(fcontent, BinaryValue):
                fcontent = fcontent.content
            if maintype == 'message' and subtype == 'rfc822':
                msg.add_attachment(BytesParser().parsebytes(fcontent), filename=fname)
            else:
                msg.add_attachment(fcontent, maintype, subtype, filename=fname)
    return msg


def _get_default_bounce_address(self):
    """ Computes the default bounce address. It is used to set the envelop
        address if no envelop address is provided in the message.

        :return: defaults to the ``--email-from`` CLI/config parameter.
        :rtype: str | None
        """
    return tools.config.get("email_from")


def _get_default_from_address(self):
    """ Computes the default from address. It is used for the "header from"
        address when no other has been received.

        :return: defaults to the ``--email-from`` CLI/config parameter.
        :rtype: str | None
        """
    return tools.config.get("email_from")


def _get_default_from_filter(self):
    """ Computes the default from_filter. It is used when no specific
        ir.mail_server is used when sending emails, hence having no value for
        from_filter.

        :return: defaults to 'mail.default.from_filter', then
          ``--from-filter`` CLI/config parameter.
        :rtype: str | None
        """
    return self.env['ir.config_parameter'].sudo().get_str(
        'mail.default.from_filter') or tools.config.get('from_filter')


def _prepare_email_message__(self, message, smtp_session):  # noqa: PLW3201
    """Prepare the SMTP information (from, to, message) before sending.

        :param message: the email.message.Message to send, information like the
            Return-Path, the From, etc... will be used to find the smtp_from and to smtp_to
        :param smtp_session: the opened SMTP session to use to authenticate the sender

        :return: smtp_from, smtp_to_list, message
            smtp_from: email to used during the authentication to the mail server
            smtp_to_list: list of email address which will receive the email
            message: the email.message.Message to send
        """
    # Use the default bounce address **only if** no Return-Path was
    # provided by caller.  Caller may be using Variable Envelope Return
    # Path (VERP) to detect no-longer valid email addresses.
    # context may force a value, e.g. mail.alias.domain usage
    bounce_address = self.env.context.get('domain_bounce_address') or message['Return-Path'] or self._get_default_bounce_address() or message['From']

    smtp_from = message['From'] or bounce_address
    assert smtp_from, self.NO_FOUND_SMTP_FROM

    smtp_to_list = self._prepare_smtp_to_list(message, smtp_session)
    assert smtp_to_list, self.NO_VALID_RECIPIENT

    # Try to not spoof the mail from headers; fetch session-based or contextualized
    # values for encapsulation computation
    from_filter = getattr(smtp_session, 'from_filter', False)
    smtp_from = getattr(smtp_session, 'smtp_from', False) or smtp_from
    notifications_email = email_normalize(
        self.env.context.get('domain_notifications_email') or self._get_default_from_address()
    )
    if notifications_email and email_normalize(smtp_from) == notifications_email and email_normalize(message['From']) != notifications_email:
        smtp_from = encapsulate_email(message['From'], notifications_email)

    # alter message
    self._alter_message__(message, smtp_from, smtp_to_list)

    # Check if it's still possible to put the bounce address as smtp_from
    if self._match_from_filter(bounce_address, from_filter):
        # Mail headers FROM will be spoofed to be able to receive bounce notifications
        # Because the mail server support the domain of the bounce address
        smtp_from = bounce_address

    # The email's "Envelope From" (Return-Path) must only contain ASCII characters.
    smtp_from_rfc2822 = extract_rfc2822_addresses(smtp_from)
    if not smtp_from_rfc2822:
        raise AssertionError(
            self.NO_VALID_FROM,
            f"Malformed 'Return-Path' or 'From' address: {smtp_from} - "
            "It should contain one valid plain ASCII email"
        )
    smtp_from = smtp_from_rfc2822[-1]

    return smtp_from, smtp_to_list, message


def _alter_message__(self, message, smtp_from, smtp_to_list):  # noqa: PLW3201
    # `To:` header forged, e.g. for posting on discuss.channels, to avoid confusion
    if x_forge_to := message['X-Forge-To']:
        message.replace_header('To', x_forge_to)
    # `To:` header extended, e.g. for adding "virtual" recipients, aka fake recipients
    # that do not impact SMTP To
    elif x_msg_add_to := message['X-Msg-To-Add']:
        to = message['To'] or ''
        to_normalized = tools.mail.email_normalize_all(to)
        message.replace_header(
            'To', ', '.join(
                ([to] if to else []) +
                [address for address in tools.mail.email_split_and_format(x_msg_add_to)
                 if tools.mail.email_normalize(address, strict=False) not in to_normalized]
            ))
    # `Cc:` header extended similarly
    if x_msg_add_cc := message.get('X-Msg-Cc-Add'):
        cc = message.get('Cc') or ''
        exclude_cc = tools.mail.email_normalize_all(cc) + tools.mail.email_normalize_all(message.get('To') or '')
        new_cc = ', '.join(
            ([cc] if cc else []) +
            [address for address in tools.mail.email_split_and_format(x_msg_add_cc)
             if tools.mail.email_normalize(address, strict=False) not in exclude_cc]
        )
        try:
            message.replace_header('Cc', new_cc)
        except KeyError:
            message.add_header('Cc', new_cc)

    if message['From'] != smtp_from:
        message.replace_header('From', smtp_from)

    # cleanup unwanted headers
    del message['Bcc']                   # see odoo/odoo@2445f9e3c22db810d61996afde883e4ca608f15b
    del message['X-Forge-To']
    del message['X-Msg-Cc-Add']
    del message['X-Msg-To-Add']
    del message['X-Msg-To-Consolidate']


def _prepare_smtp_to_list(self, message, smtp_session):
    """ Prepare SMTP To address list, based on To / Cc / Bcc.

        Optional 'send_validated_to' context key filter restricts addresses to
        be part of that list.
        
        Optional 'send_smtp_skip_to' context key holds a recipients block list
        """
    email_to = message['To']
    email_cc = message['Cc']
    email_bcc = message['Bcc']

    # Support optional pre-validated To list, used notably when formatted
    # emails may create fake emails using extract_rfc2822_addresses, e.g.
    # '"Bike@Home" <email@domain.com>' which can be considered as containing
    # 2 emails by extract_rfc2822_addresses
    validated_to = self.env.context.get('send_validated_to') or []

    # Support optional skip To list
    skip_to_lst = self.env.context.get('send_smtp_skip_to') or []

    # All recipient addresses must only contain ASCII characters
    return [
        address
        for base in [email_to, email_cc, email_bcc]
        # be sure a given address does not return duplicates (but duplicates
        # in final smtp to list is still ok)
        for address in tools.misc.unique(extract_rfc2822_addresses(base))
        if (
            address and (not validated_to or address in validated_to)
            and email_normalize(address, strict=False) not in skip_to_lst
        )
    ]
