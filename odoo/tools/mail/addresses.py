"""Email addresses and headers: parsing, normalizing and anonymizing the addresses, and the message ids."""

import base64
import random
import re
import socket
import time
import email.utils
from email.utils import getaddresses as orig_getaddresses
import idna


if hasattr(email.utils, 'supports_strict_parsing'):
    def getaddresses(fieldvalues):
        return orig_getaddresses(fieldvalues, strict=False)
else:
    getaddresses = orig_getaddresses


email_re = re.compile(r"""([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,63})""", re.VERBOSE)


single_email_re = re.compile(r"""^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,63}$""", re.VERBOSE)


mail_header_msgid_re = re.compile('<[^<>]+>')


email_addr_escapes_re = re.compile(r'[\\"]')


def generate_tracking_message_id(res_id):
    """Returns a string that can be used in the Message-ID RFC822 header field

       Used to track the replies related to a given object thanks to the "In-Reply-To"
       or "References" fields that Mail User Agents will set.
    """
    try:
        rnd = random.SystemRandom().random()
    except NotImplementedError:
        rnd = random.random()
    rndstr = ("%.15f" % rnd)[2:]
    return "<%s.%.15f-openerp-%s@%s>" % (rndstr, time.time(), res_id, socket.gethostname())


def email_split_tuples(text):
    """ Return a list of (name, email) address tuples found in ``text`` . Note
    that text should be an email header or a stringified email list as it may
    give broader results than expected on actual text. """
    def _parse_based_on_spaces(pair):
        """ With input 'name email@domain.com' (missing quotes for a formatting)
        getaddresses returns ('', 'name email@domain.com). This when having no
        name and an email a fallback to enhance parsing is to redo a getaddresses
        by replacing spaces by commas. The new email will be split into sub pairs
        allowing to find the email and name parts, allowing to make a new name /
        email pair. Emails should not contain spaces thus this is coherent with
        email formation. """
        name, email = pair
        if not name and email and ' ' in email:
            inside_pairs = getaddresses([email.replace(' ', ',')])
            name_parts, found_email = [], False
            for pair in inside_pairs:
                if pair[1] and '@' not in pair[1]:
                    name_parts.append(pair[1])
                if pair[1] and '@' in pair[1]:
                    found_email = pair[1]
            name, email = (' '.join(name_parts), found_email) if found_email else (name, email)
        return (name, email)

    if not text:
        return []

    # found valid pairs, filtering out failed parsing
    valid_pairs = [
        (addr[0], addr[1]) for addr in getaddresses([text])
        # getaddresses() returns '' when email parsing fails, and
        # sometimes returns emails without at least '@'. The '@'
        # is strictly required in RFC2822's `addr-spec`.
        if addr[1] and '@' in addr[1]
    ]
    # corner case: returning '@gmail.com'-like email (see test_email_split)
    if any(pair[1].startswith('@') for pair in valid_pairs):
        filtered = [
            found_email for found_email in email_re.findall(text)
            if found_email and not found_email.startswith('@')
        ]
        if filtered:
            valid_pairs = [('', found_email) for found_email in filtered]

    return list(map(_parse_based_on_spaces, valid_pairs))


def email_split(text):
    """ Return a list of the email addresses found in ``text`` """
    return [email for (name, email) in email_split_tuples(text)]


def email_split_and_format(text):
    """ Return a list of email addresses found in ``text``, formatted using
    formataddr. """
    return [formataddr((name, email)) for (name, email) in email_split_tuples(text)]


def email_split_and_normalize(text):
    """ Same as 'email_split' but normalized email """
    return [(name, _normalize_email(email)) for (name, email) in email_split_tuples(text)]


def email_split_and_format_normalize(text):
    """ Same as 'email_split_and_format' but normalizing email. """
    return [
        formataddr(
            (name, _normalize_email(email))
        ) for (name, email) in email_split_tuples(text)
    ]


def email_normalize(text, strict=True):
    """ Sanitize and standardize email address entries. As of rfc5322 section
    3.4.1 local-part is case-sensitive. However most main providers do consider
    the local-part as case insensitive. With the introduction of smtp-utf8
    within odoo, this assumption is certain to fall short for international
    emails. We now consider that

      * if local part is ascii: normalize still 'lower' ;
      * else: use as it, SMTP-UF8 is made for non-ascii local parts;

    Concerning domain part of the address, as of v14 international domain (IDNA)
    are handled fine. The domain is always lowercase, lowering it is fine as it
    is probably an error. With the introduction of IDNA, there is an encoding
    that allow non-ascii characters to be encoded to ascii ones, using 'idna.encode'.

    A normalized email is considered as :
    - having a left part + @ + a right part (the domain can be without '.something')
    - having no name before the address. Typically, having no 'Name <>'
    Ex:
    - Possible Input Email : 'Name <NaMe@DoMaIn.CoM>'
    - Normalized Output Email : 'name@domain.com'

    :param boolean strict: if True, text should contain a single email
      (default behavior in stable 14+). If more than one email is found no
      normalized email is returned. If False the first found candidate is used
      e.g. if email is 'tony@e.com, "Tony2" <tony2@e.com>', result is either
      False (strict=True), either 'tony@e.com' (strict=False).

    :return: False if no email found (or if more than 1 email found when being
      in strict mode); normalized email otherwise;
    """
    emails = email_split(text)
    if not emails or (strict and len(emails) != 1):
        return False
    return _normalize_email(emails[0])


def email_normalize_all(text):
    """ Tool method allowing to extract email addresses from a text input and returning
    normalized version of all found emails. If no email is found, a void list
    is returned.

    e.g. if email is 'tony@e.com, "Tony2" <tony2@e.com' returned result is ['tony@e.com, tony2@e.com']

    :return list: list of normalized emails found in text
    """
    emails = email_split(text)
    return list(filter(None, [_normalize_email(email) for email in emails]))


def _normalize_email(email):
    """ As of rfc5322 section 3.4.1 local-part is case-sensitive. However most
    main providers do consider the local-part as case insensitive. With the
    introduction of smtp-utf8 within odoo, this assumption is certain to fall
    short for international emails. We now consider that

      * if local part is ascii: normalize still 'lower' ;
      * else: use as it, SMTP-UF8 is made for non-ascii local parts;

    Concerning domain part of the address, as of v14 international domain (IDNA)
    are handled fine. The domain is always lowercase, lowering it is fine as it
    is probably an error. With the introduction of IDNA, there is an encoding
    that allow non-ascii characters to be encoded to ascii ones, using 'idna.encode'.

    A normalized email is considered as :
    - having a left part + @ + a right part (the domain can be without '.something')
    - having no name before the address. Typically, having no 'Name <>'
    Ex:
    - Possible Input Email : 'Name <NaMe@DoMaIn.CoM>'
    - Normalized Output Email : 'name@domain.com'
    """
    local_part, at, domain = email.rpartition('@')
    try:
        local_part.encode('ascii')
    except UnicodeEncodeError:
        pass
    else:
        local_part = local_part.lower()

    return local_part + at + domain.lower()


def email_anonymize(normalized_email, *, redact_domain=False):
    """
    Replace most charaters in the local part of the email address with
    '*' to hide the recipient, but keep enough characters for debugging
    purpose.

    The email address must be normalized already.

    >>> email_anonymize('admin@example.com')
    'a****@example.com'
    >>> email_anonymize('portal@example.com')
    'p***al@example.com'
    >>> email_anonymize('portal@example.com', redact_domain=True)
    'p***al@e******.com'
    """
    if not normalized_email:
        return normalized_email

    local, at, domain = normalized_email.partition('@')
    if len(local) <= 5:
        anon_local = local[:1] + '*' * (len(local) - 1)
    else:
        anon_local = local[:1] + '*' * (len(local) - 3) + local[-2:]

    host, dot, tld = domain.rpartition('.')
    if redact_domain and not domain.startswith('[') and all((host, dot, tld)):
        anon_host = host[0] + '*' * (len(host) - 1)
    else:
        anon_host = host

    return f'{anon_local}{at}{anon_host}{dot}{tld}'


def email_domain_extract(email):
    """ Extract the company domain to be used by IAP services notably. Domain
    is extracted from email information e.g:

    - info@proximus.be -> proximus.be
    """
    normalized_email = email_normalize(email)
    if normalized_email:
        return normalized_email.split('@')[1]
    return False


def email_domain_normalize(domain):
    """Return the domain normalized or False if the domain is invalid."""
    if not domain or '@' in domain:
        return False

    return domain.lower()


def email_escape_char(email_address):
    """ Escape problematic characters in the given email address string"""
    return email_address.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')


def decode_message_header(message, header, separator=' '):
    return separator.join(h for h in message.get_all(header, []) if h)


def formataddr(pair, charset='utf-8'):
    """Pretty format a 2-tuple of the form (realname, email_address).

    If the first element of pair is falsy then only the email address
    is returned.

    Set the charset to ascii to get a RFC-2822 compliant email. The
    realname will be base64 encoded (if necessary) and the domain part
    of the email will be punycode encoded (if necessary). The local part
    is left unchanged thus require the SMTPUTF8 extension when there are
    non-ascii characters.

    >>> formataddr(('John Doe', 'johndoe@example.com'))
    '"John Doe" <johndoe@example.com>'

    >>> formataddr(('', 'johndoe@example.com'))
    'johndoe@example.com'
    """
    name, address = pair
    local, _, domain = address.rpartition('@')

    try:
        domain.encode(charset)
    except UnicodeEncodeError:
        # rfc5890 - Internationalized Domain Names for Applications (IDNA)
        domain = idna.encode(domain).decode('ascii')

    if name:
        try:
            name.encode(charset)
        except UnicodeEncodeError:
            # charset mismatch, encode as utf-8/base64
            # rfc2047 - MIME Message Header Extensions for Non-ASCII Text
            name = base64.b64encode(name.encode('utf-8')).decode('ascii')
            return f"=?utf-8?b?{name}?= <{local}@{domain}>"
        else:
            # ascii name, escape it if needed
            # rfc2822 - Internet Message Format
            #   #section-3.4 - Address Specification
            name = email_addr_escapes_re.sub(r'\\\g<0>', name)
            return f'"{name}" <{local}@{domain}>'
    return f"{local}@{domain}"


def encapsulate_email(old_email, new_email):
    """Change the FROM of the message and use the old one as name.

    e.g.
    * Old From: "Admin" <admin@gmail.com>
    * New From: notifications@odoo.com
    * Output: "Admin" <notifications@odoo.com>
    """
    old_email_split = getaddresses([old_email])
    if not old_email_split or not old_email_split[0]:
        return old_email

    new_email_split = getaddresses([new_email])
    if not new_email_split or not new_email_split[0]:
        return

    old_name, old_email = old_email_split[0]
    if old_name:
        name_part = old_name
    else:
        name_part = old_email.split("@")[0]

    return formataddr((
        name_part,
        new_email_split[0][1],
    ))


def parse_contact_from_email(text):
    """ Parse contact name and email (given by text) in order to find contact
    information, able to populate records like partners, leads, ...
    Supported syntax:

      * Raoul <raoul@grosbedon.fr>
      * "Raoul le Grand" <raoul@grosbedon.fr>
      * Raoul raoul@grosbedon.fr (strange fault tolerant support from
        df40926d2a57c101a3e2d221ecfd08fbb4fea30e now supported directly
        in 'email_split_tuples';

    Otherwise: default, text is set as name.

    :return: name, email (normalized if possible)
    """
    if not text or not text.strip():
        return '', ''
    split_results = email_split_tuples(text)
    name, email = split_results[0] if split_results else ('', '')

    if email:
        email_normalized = email_normalize(email, strict=False) or email
    else:
        name, email_normalized = text, ''

    return name, email_normalized


def unfold_references(msg_references):
    """ As it declared in [RFC2822] long header bodies can be "folded" using
    CRLF+WSP. Some mail clients split References header body which contains
    Message Ids by "\n ".

    RFC2882: https://tools.ietf.org/html/rfc2822#section-2.2.3 """
    return [
        re.sub(r'[\r\n\t ]+', r'', ref)  # "Unfold" buggy references
        for ref in mail_header_msgid_re.findall(msg_references)
    ]
