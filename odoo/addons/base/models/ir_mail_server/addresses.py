# Part of Odoo. See LICENSE file for full copyright and licensing details.

import re

import idna

from odoo.tools import (
    formataddr,
)


def is_ascii(s):
    return all(ord(cp) < 128 for cp in s)

address_pattern = re.compile(r'([^" ,<@]+@[^>" ,]+)')

def extract_rfc2822_addresses(text):
    """Returns a list of valid RFC2822 addresses
       that can be found in ``source``, ignoring
       malformed ones and non-ASCII ones.
    """
    if not text:
        return []
    candidates = address_pattern.findall(text)
    valid_addresses = []
    for c in candidates:
        try:
            valid_addresses.append(formataddr(('', c), charset='ascii'))
        except idna.IDNAError:
            pass
    return valid_addresses
