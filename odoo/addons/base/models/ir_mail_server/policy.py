# Part of Odoo. See LICENSE file for full copyright and licensing details.

import email.policy




# Python 3: workaround for bpo-35805, only partially fixed in Python 3.8.
RFC5322_IDENTIFICATION_HEADERS = {'message-id', 'in-reply-to', 'references', 'resent-msg-id'}
USER_DEFINED_HEADERS = {'bcc', 'cc', 'from', 'reply-to', 'subject', 'to'}
_noFoldPolicy = email.policy.SMTP.clone(max_line_length=None)
_maxFoldPolicy = email.policy.SMTP.clone(max_line_length=998)  # rfc5322#section-2.1.1
class IdentificationFieldsNoFoldPolicy(email.policy.EmailPolicy):
    # Override _fold() to avoid folding identification fields, excluded by RFC2047 section 5
    # These are particularly important to preserve, as MTAs will often rewrite non-conformant
    # Message-ID headers, causing a loss of thread information (replies are lost)
    # Also override _fold() for user-defined headers that may not fit on 78 characters,
    # as Python's folding algorithm is unreliable and fail to handle all weird cases.
    def _fold(self, name, value, *args, **kwargs):
        if name.lower() in RFC5322_IDENTIFICATION_HEADERS:
            return _noFoldPolicy._fold(name, value, *args, **kwargs)
        if name.lower() in USER_DEFINED_HEADERS:
            return _maxFoldPolicy._fold(name, value, *args, **kwargs)
        return super()._fold(name, value, *args, **kwargs)

# Global monkey-patch for our preferred SMTP policy, preserving the non-default linesep
email.policy.SMTP = IdentificationFieldsNoFoldPolicy(linesep=email.policy.SMTP.linesep)
