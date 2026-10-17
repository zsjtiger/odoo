# Part of Odoo. See LICENSE file for full copyright and licensing details.
"""Markdown and HTML formatting of AI answers."""
from lxml import html

from odoo.tools import html_sanitize

from .custom_markdown import CustomMarkdown


def markdown_format(text):
    if CustomMarkdown:
        raw_html = CustomMarkdown(
            extras=['fenced-code-blocks', 'tables', 'strike', 'cuddled-lists', 'highlightjs-lang', 'break-on-newline'],
        ).convert(text).strip()
        text = format_html_response(raw_html)
    return html_sanitize(text, sanitize_attributes=True, sanitize_style=True)


def format_html_response(html_string):
    if not html_string:
        return None
    html_tree = html.fromstring(html_string)
    class_map = {
        "table": "table o_table table-light table-hover o-scrollbar-thin table-bordered ai-table-response my-2",
        "thead": "table-secondary",
        "pre": "ai-pre-response o-scrollbar-thin",
        "code": "ai-code-response",
    }
    for element in html_tree.xpath("//table | //thead | //pre | //code"):
        element.attrib["class"] = f'{element.attrib.get("class", "")} {class_map[element.tag]}'

    # If the root element is a div and the original string did not start with a div,
    # it means lxml.html.fromstring added an implicit wrapper. We unwrap it.
    if html_tree.tag == 'div' and not html_string.strip().lower().startswith('<div'):
        return ''.join(html.tostring(child, encoding='unicode', method='html') for child in html_tree.iterchildren())
    return html.tostring(html_tree, encoding='unicode', method='html')
