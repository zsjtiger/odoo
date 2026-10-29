"""Conversions between HTML and plain text, and the checks and the cleanup of the links of the HTML."""

import itertools
import re
from collections.abc import Buffer
from typing import Literal
import html as htmllib
import markupsafe
from lxml import etree, html
from odoo.tools import misc
from ..links import URL_REGEX

from .sanitize import html_sanitize, lxml_remove_element_preserve_tail

HTML_TAG_URL_REGEX = URL_REGEX + r'([^<>]*>([^<>]+)<\/)?'


HTML_TAGS_REGEX = re.compile('<.*?>')


HTML_NEWLINES_REGEX = re.compile('<(div|p|br|tr)[^>]*>|\n')


def is_html_empty(html_content: str | markupsafe.Markup | Literal[False] | None) -> bool:
    """Check if a html content is empty. If there are only formatting tags with style
    attributes or a void content  return True. Famous use case if a
    '<p style="..."><br></p>' added by some web editor.

    :param html_content: html content, coming from example from an HTML field
    :returns: True if no content found or if containing only void formatting tags
    """
    if not html_content:
        return True
    icon_re = r'<\s*(i|span)\b(\s+[A-Za-z_-][A-Za-z0-9-_]*(\s*=\s*[\'"][^"\']*[\'"])?)*\s*\bclass\s*=\s*["\'][^"\']*\b(fa|fab|fad|far|oi)\b'
    tag_re = r'<\s*\/?(?:p|div|section|span|br|b|i|font)\b(?:(\s+[A-Za-z_-][A-Za-z0-9-_]*(\s*=\s*[\'"][^"\']*[\'"]))*)(?:\s*>|\s*\/\s*>)'
    text_content = htmllib.unescape(re.sub(tag_re, '', html_content))
    return not bool(text_content.strip()) and not re.search(icon_re, html_content)


def html_keep_url(text):
    """ Transform the url into clickable link with <a/> tag """
    idx = 0
    final = ''
    link_tags = re.compile(r"""(?<!["'])((ftp|http|https):\/\/(\w+:{0,1}\w*@)?([^\s<"']+)(:[0-9]+)?(\/|\/([^\s<"']))?)(?![^\s<"']*["']|[^\s<"']*</a>)""")
    for item in re.finditer(link_tags, text):
        final += text[idx:item.start()]
        final += create_link(item.group(0), item.group(0))
        idx = item.end()
    final += text[idx:]
    return final


def html_remove_links(body):
    """Replace every ``<a>`` by its text content followed by its target.

    ``<a href="https://odoo.com">Odoo</a>`` becomes ``Odoo (https://odoo.com)``.

    Intended for content displayed inertly (e.g. sandboxed previews of files
    uploaded by users).
    """
    if not body or not body.strip():
        return body
    root = html.fragment_fromstring(body, create_parent='div')
    for link in list(root.iter('a')):
        href = (link.get('href') or '').strip()
        if href and not href.startswith('#'):
            link.tail = f' ({href}){link.tail or ""}'
        link.drop_tag()
    result = html.tostring(root, encoding='unicode')[5:-6]
    return markupsafe.Markup(result) if isinstance(body, markupsafe.Markup) else result


def html_remove_xpath(body, xpath_expression):
    """Remove all elements matching some xpath."""
    BodyClass = type(body)
    parsed_body_root = html.fragment_fromstring(body, create_parent='div')
    xpath_elements = parsed_body_root.xpath(xpath_expression)
    for element in xpath_elements:
        if element != parsed_body_root:
            lxml_remove_element_preserve_tail(element)
    # if the input body was already a single node with no trailing string, avoid adding wrapper div
    root_children = parsed_body_root.getchildren()
    if len(root_children) == 1 and not root_children[0].tail:
        parsed_body_root = root_children[0]
    final_body = html.tostring(parsed_body_root, encoding='unicode')
    return BodyClass(final_body)


def html_to_inner_content(html):
    """Returns unformatted text after removing html tags and excessive whitespace from a
    string/Markup. Passed strings will first be sanitized.
    """
    if is_html_empty(html):
        return ''
    if not isinstance(html, markupsafe.Markup):
        html = html_sanitize(html)
    processed = re.sub(HTML_NEWLINES_REGEX, ' ', html)
    processed = re.sub(HTML_TAGS_REGEX, '', processed)
    processed = re.sub(r' {2,}|\t', ' ', processed)
    processed = processed.replace("\xa0", " ")
    processed = htmllib.unescape(processed)
    return processed.strip()


def create_link(url, label):
    return f'<a href="{url}" target="_blank" rel="noreferrer noopener">{label}</a>'


def html2plaintext(
    html: str | markupsafe.Markup | Literal[False] | None,
    body_id: str | None = None,
    encoding: str = 'utf-8',
    include_references: bool = True
) -> str:
    """ From an HTML text, convert the HTML to plain text.
    If @param body_id is provided then this is the tag where the
    body (not necessarily <body>) starts.
    :param include_references: If False, numbered references and
        URLs for links and images will not be included.
    """
    ## (c) Fry-IT, www.fry-it.com, 2007
    ## <peter@fry-it.com>
    ## download here: http://www.peterbe.com/plog/html2plaintext
    if not (html and html.strip()):
        return ''

    if isinstance(html, Buffer):
        html = bytes(html).decode(encoding)
    else:
        assert isinstance(html, str), f"expected str got {html.__class__.__name__}"

    tree = etree.fromstring(html, parser=etree.HTMLParser())

    if body_id is not None:
        source = tree.xpath('//*[@id=%s]' % (body_id,))
    else:
        source = tree.xpath('//body')
    if len(source):
        tree = source[0]

    url_index = []
    linkrefs = itertools.count(1)
    if include_references:
        for link in tree.findall('.//a'):
            if url := link.get('href'):
                link.tag = 'span'
                link.text = f'{link.text} [{next(linkrefs)}]'
                url_index.append(url)

        for img in tree.findall('.//img'):
            if src := img.get('src'):
                img.tag = 'span'
                if src.startswith('data:'):
                    img_name = None  # base64 image
                else:
                    img_name = re.search(r'[^/]+(?=\.[a-zA-Z]+(?:\?|$))', src)
                img.text = '%s [%s]' % (img_name[0] if img_name else 'Image', next(linkrefs))
                url_index.append(src)

    html = etree.tostring(tree, encoding="unicode")
    # \r char is converted into &#13;, must remove it
    html = html.replace('&#13;', '')

    html = html.replace('<strong>', '*').replace('</strong>', '*')
    html = html.replace('<b>', '*').replace('</b>', '*')
    html = html.replace('<h3>', '*').replace('</h3>', '*')
    html = html.replace('<h2>', '**').replace('</h2>', '**')
    html = html.replace('<h1>', '**').replace('</h1>', '**')
    html = html.replace('<em>', '/').replace('</em>', '/')
    html = html.replace('<tr>', '\n')
    html = html.replace('</p>', '\n')
    html = re.sub(r'<br\s*/?>', '\n', html)
    html = re.sub('<.*?>', ' ', html)
    html = html.replace(' ' * 2, ' ')
    html = html.replace('&gt;', '>')
    html = html.replace('&lt;', '<')
    html = html.replace('&amp;', '&')
    html = html.replace('&nbsp;', '\N{NO-BREAK SPACE}')

    # strip all lines
    html = '\n'.join([x.strip() for x in html.splitlines()])
    html = html.replace('\n' * 2, '\n')

    if url_index:
        html += '\n\n'
        for i, url in enumerate(url_index, start=1):
            html += f'[{i}] {url}\n'

    return html.strip()


def plaintext2html(text: str, container_tag: str | None = None, with_paragraph: bool = True) -> markupsafe.Markup:
    r"""Convert plaintext into html. Content of the text is escaped to manage
    html entities, using :func:`~odoo.tools.misc.html_escape`.

    - all ``\n``, ``\r`` are replaced by ``<br/>``
    - convert url into clickable link

    :param text: plaintext to convert
    :param container_tag: container of the html; by default the content is
        embedded into a ``<div>``
    :param with_paragraph: whether or not considering 2 or more consecutive ``<br/>``
        as paragraph breaks and enclosing content in ``<p>``
    """
    assert isinstance(text, str)
    text = misc.html_escape(text)

    # 1. replace \n and \r
    text = re.sub(r'(\r\n|\r|\n)', '<br/>', text)

    # 2. clickable links
    text = html_keep_url(text)

    # 3-4: form paragraphs
    final = text
    if with_paragraph:
        idx = 0
        final = '<p>'
        br_tags = re.compile(r'(([<]\s*[bB][rR]\s*/?[>]\s*){2,})')
        for item in re.finditer(br_tags, text):
            final += text[idx:item.start()] + '</p><p>'
            idx = item.end()
        final += text[idx:] + '</p>'

    # 5. container
    if container_tag: # FIXME: validate that container_tag is just a simple tag?
        final = '<%s>%s</%s>' % (container_tag, final, container_tag)
    return markupsafe.Markup(final)
