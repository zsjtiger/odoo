# Part of Odoo. See LICENSE file for full copyright and licensing details.
# ruff: noqa: F401
"""Backport of the URL functions and classes that werkzeug 3.0 removed from werkzeug.urls, split by concern. The names are re-exported here."""

from .helpers import _check_str_tuple, _default_encoding, _make_encode_wrapper, _to_str
from .charsets import _always_safe, _always_safe_chars, _bytetohex, _hexdigits, _hextobyte, _scheme_re
from .classes import BaseURL, BytesURL, URL, _URLTuple, url_join, url_parse, url_unparse
from .quote import _fast_quote_plus, _fast_url_quote_plus, _make_fast_url_quote, _unquote_to_bytes, url_quote, url_quote_plus, url_unquote, url_unquote_plus
from .query import _url_decode_impl, _url_encode_impl, _url_unquote_legacy, url_decode, url_encode

__all__ = [
    'BaseURL',
    'BytesURL',
    'URL',
    'url_decode',
    'url_encode',
    'url_join',
    'url_parse',
    'url_quote',
    'url_quote_plus',
    'url_unparse',
    'url_unquote',
    'url_unquote_plus',
]
