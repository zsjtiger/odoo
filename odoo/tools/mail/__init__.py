# Part of Odoo. See LICENSE file for full copyright and licensing details.
# ruff: noqa: F401
"""Mail tools used by Odoo, split by concern: the HTML, the links and the email addresses. The names are re-exported here."""

from .html import HTML_NEWLINES_REGEX, HTML_TAGS_REGEX, HTML_TAG_URL_REGEX, SANITIZE_TAGS, _Cleaner, append_content_to_html, create_link, fromstring, html2plaintext, html_keep_url, html_normalize, html_remove_links, html_remove_xpath, html_sanitize, html_to_inner_content, is_html_empty, lxml_remove_element_preserve_tail, plaintext2html, prepend_html_content, safe_attrs, tag_quote
from .links import TEXT_URL_ALLOWED_GROUP, TEXT_URL_REGEX, URL_REGEX, URL_SKIP_PROTOCOL_REGEX, text_url_replace, url_domain_extract, validate_url
from .addresses import _normalize_email, decode_message_header, email_addr_escapes_re, email_anonymize, email_domain_extract, email_domain_normalize, email_escape_char, email_normalize, email_normalize_all, email_re, email_split, email_split_and_format, email_split_and_format_normalize, email_split_and_normalize, email_split_tuples, encapsulate_email, formataddr, generate_tracking_message_id, mail_header_msgid_re, parse_contact_from_email, single_email_re, unfold_references

__all__ = [
    'email_domain_extract',
    'email_domain_normalize',
    'email_normalize',
    'email_normalize_all',
    'email_split',
    'encapsulate_email',
    'formataddr',
    'html2plaintext',
    'html_normalize',
    'html_sanitize',
    'is_html_empty',
    'parse_contact_from_email',
    'plaintext2html',
    'single_email_re',
]
