# Part of Odoo. See LICENSE file for full copyright and licensing details.
# ruff: noqa: F401
"""HTML of the messages, split by concern: the sanitizing, the plain text conversions and the content insertion. The names are re-exported here."""

from .sanitize import SANITIZE_TAGS, _Cleaner, fromstring, html_normalize, html_sanitize, lxml_remove_element_preserve_tail, safe_attrs, tag_quote
from .plaintext import HTML_NEWLINES_REGEX, HTML_TAGS_REGEX, HTML_TAG_URL_REGEX, create_link, html2plaintext, html_keep_url, html_remove_links, html_remove_xpath, html_to_inner_content, is_html_empty, plaintext2html
from .content import append_content_to_html, prepend_html_content

__all__ = [
    'HTML_NEWLINES_REGEX',
    'HTML_TAGS_REGEX',
    'HTML_TAG_URL_REGEX',
    'SANITIZE_TAGS',
    'append_content_to_html',
    'create_link',
    'fromstring',
    'html2plaintext',
    'html_keep_url',
    'html_normalize',
    'html_remove_links',
    'html_remove_xpath',
    'html_sanitize',
    'html_to_inner_content',
    'is_html_empty',
    'lxml_remove_element_preserve_tail',
    'plaintext2html',
    'prepend_html_content',
    'safe_attrs',
    'tag_quote',
]
