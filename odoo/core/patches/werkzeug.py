# Part of Odoo. See LICENSE file for full copyright and licensing details.
"""Patches of werkzeug 3.0.1.

The URL functions of ``werkzeug.urls`` removed in werkzeug 3.0 are backported
from ``_werkzeug_urls``; the other patches fix the objects of werkzeug.
"""
from werkzeug import urls
from werkzeug.datastructures import WWWAuthenticate
from werkzeug.wrappers import Request, Response

from ._werkzeug_urls import (
    URL,
    url_decode,
    url_encode,
    url_join,
    url_parse,
    url_quote,
    url_quote_plus,
    url_unparse,
    url_unquote,
    url_unquote_plus,
)


def patch_module():
    from odoo.tools.json import scriptsafe
    Request.json_module = Response.json_module = scriptsafe

    # https://github.com/pallets/werkzeug/issues/3127
    def _stripped_to_header(*args, **kwargs):
        return orig_to_header(*args, **kwargs).rstrip()
    orig_to_header = WWWAuthenticate.to_header
    WWWAuthenticate.to_header = _stripped_to_header

    if hasattr(urls, 'url_parse'):
        # URLs are already patched
        return
    # see https://github.com/pallets/werkzeug/compare/2.3.0..3.0.0
    urls.URL = URL
    urls.url_decode = url_decode
    urls.url_encode = url_encode
    urls.url_join = url_join
    urls.url_parse = url_parse
    urls.url_quote = url_quote
    urls.url_quote_plus = url_quote_plus
    urls.url_unparse = url_unparse
    urls.url_unquote = url_unquote
    urls.url_unquote_plus = url_unquote_plus
