"""HTML of the messages: the sanitizing, the normalizing and the conversions to and from plain text."""

import collections
import itertools
import logging
import re
from collections.abc import Buffer
from typing import Literal
import html as htmllib
import markupsafe
from lxml import etree, html
from lxml.html import (
    XHTML_NAMESPACE,
    _contains_block_level_tag,
    _looks_like_full_html_bytes,
    _looks_like_full_html_unicode,
    clean,
    defs,
    html_parser,
)
from odoo.tools import misc

from .links import URL_REGEX

safe_attrs = defs.safe_attrs | frozenset(
    ['style',
     'data-o-mail-quote', 'data-o-mail-quote-node',  # quote detection
     'data-o-mail-full-composer',  # body composed with the full composer
     'data-oe-model', 'data-oe-id', 'data-oe-field', 'data-oe-type', 'data-oe-expression', 'data-oe-translation-source-sha', 'data-oe-nodeid',
     'data-last-history-commits', 'data-oe-protected', 'data-embedded', 'data-embedded-editable', 'data-embedded-props', 'data-oe-version',
     'data-oe-transient-content', 'data-behavior-props', 'data-prop-name', 'data-width', 'data-height', 'data-scale-x', 'data-scale-y', 'data-x', 'data-y',  # legacy editor
     'data-oe-role', 'data-oe-aria-label', 'data-o-datetime',
     'data-publish', 'data-id', 'data-res_id', 'data-interval', 'data-member_id', 'data-scroll-background-ratio', 'data-view-id',
     'data-class', 'data-mimetype', 'data-original-src', 'data-original-id', 'data-gl-filter', 'data-quality', 'data-resize-width',
     'data-shape', 'data-shape-colors', 'data-file-name', 'data-original-mimetype',
     'data-attachment-id', 'data-format-mimetype',
     'data-ai-field', 'data-ai-record-id',
     'data-heading-link-id',
     'data-mimetype-before-conversion',
     'data-language-id',
     'data-bs-toggle',  # support nav-tabs
     'data-icon',
     ])


defs.link_attrs |= {'xlink:href'}


SANITIZE_TAGS = {
    # allow new semantic HTML5 tags
    'allow_tags': defs.tags | frozenset('article bdi section header footer hgroup nav aside figure main'.split() + [etree.Comment]),
    'kill_tags': ['base', 'embed', 'frame', 'head', 'iframe', 'link', 'meta',
                  'noscript', 'object', 'script', 'style', 'title'],
    'remove_tags': ['html', 'body'],
}


class _Cleaner(clean.Cleaner):

    _style_re = re.compile(r'''([\w-]+)\s*:\s*((?:[^;"']|"[^";]*"|'[^';]*')+)''')

    _style_whitelist = [
        'font-size', 'font-family', 'font-weight', 'font-style', 'background-color', 'color', 'text-align',
        'line-height', 'letter-spacing', 'text-transform', 'text-decoration', 'text-decoration', 'opacity',
        'float', 'vertical-align', 'display', 'object-fit', 'direction',
        'padding', 'padding-top', 'padding-left', 'padding-bottom', 'padding-right',
        'margin', 'margin-top', 'margin-left', 'margin-bottom', 'margin-right',
        'white-space',
        # appearance
        'background-image', 'background-position', 'background-size', 'background-repeat', 'background-origin',
        # box model
        'border', 'border-color', 'border-radius', 'border-style', 'border-width', 'border-top', 'border-bottom',
        'height', 'width', 'max-width', 'min-width', 'min-height',
        # tables
        'border-collapse', 'border-spacing', 'caption-side', 'empty-cells', 'table-layout']

    _style_whitelist.extend(
        ['border-%s-%s' % (position, attribute)
            for position in ['top', 'bottom', 'left', 'right']
            for attribute in ('style', 'color', 'width', 'left-radius', 'right-radius')]
    )

    strip_classes = False
    sanitize_style = False
    conditional_comments = True

    def __call__(self, doc):
        super(_Cleaner, self).__call__(doc)

        # if we keep attributes but still remove classes
        if not getattr(self, 'safe_attrs_only', False) and self.strip_classes:
            for el in doc.iter(tag=etree.Element):
                self.strip_class(el)

        # if we keep style attribute, sanitize them
        if not self.style and self.sanitize_style:
            for el in doc.iter(tag=etree.Element):
                self.parse_style(el)

    def strip_class(self, el):
        if el.attrib.get('class'):
            del el.attrib['class']

    def parse_style(self, el):
        attributes = el.attrib
        styling = attributes.get('style')
        if styling:
            valid_styles = collections.OrderedDict()
            styles = self._style_re.findall(styling)
            for style in styles:
                if style[0].lower() in self._style_whitelist:
                    valid_styles[style[0].lower()] = style[1]
            if valid_styles:
                el.attrib['style'] = '; '.join('%s:%s' % (key, val) for (key, val) in valid_styles.items())
            else:
                del el.attrib['style']

    def kill_conditional_comments(self, doc):
        """Override the default behavior of lxml.

        https://github.com/lxml/lxml/blob/e82c9153c4a7d505480b94c60b9a84d79d948efb/src/lxml/html/clean.py#L501-L510

        In some use cases, e.g. templates used for mass mailing,
        we send emails containing conditional comments targeting Microsoft Outlook,
        to give special styling instructions.
        https://github.com/odoo/odoo/pull/119325/files#r1301064789

        Within these conditional comments, unsanitized HTML can lie.
        However, in modern browser, these comments are considered as simple comments,
        their content is not executed.
        https://caniuse.com/sr_ie-features
        """
        if self.conditional_comments:
            super().kill_conditional_comments(doc)


def tag_quote(el):
    def _create_new_node(tag, text, tail=None, attrs=None):
        new_node = etree.Element(tag)
        new_node.text = text
        new_node.tail = tail
        if attrs:
            for key, val in attrs.items():
                new_node.set(key, val)
        return new_node

    def _tag_matching_regex_in_text(regex, node, tag='span', attrs=None):
        text = node.text or ''
        if not re.search(regex, text):
            return

        child_node = None
        idx, node_idx = 0, 0
        for item in re.finditer(regex, text):
            new_node = _create_new_node(tag, text[item.start():item.end()], None, attrs)
            if child_node is None:
                node.text = text[idx:item.start()]
                new_node.tail = text[item.end():]
                node.insert(node_idx, new_node)
            else:
                child_node.tail = text[idx:item.start()]
                new_node.tail = text[item.end():]
                node.insert(node_idx, new_node)
            child_node = new_node
            idx = item.end()
            node_idx = node_idx + 1

    el_class = el.get('class', '') or ''
    el_id = el.get('id', '') or ''

    # gmail or yahoo // # outlook, html // # msoffice
    if 'gmail_extra' in el_class or \
            ('SkyDrivePlaceholder' in el_class or 'SkyDrivePlaceholder' in el_class):
        if el.tag != 't':
            el.set('data-o-mail-quote', '1')
        if el.getparent() is not None and el.getparent().tag != 't':
            el.getparent().set('data-o-mail-quote-container', '1')

    if (el.tag == 'hr' and ('stopSpelling' in el_class or 'stopSpelling' in el_id)) or \
       'yahoo_quoted' in el_class:
        # Quote all elements after this one
        if el.tag != 't':
            el.set('data-o-mail-quote', '1')
        for sibling in el.itersiblings(preceding=False):
            sibling.set('data-o-mail-quote', '1')

    # odoo, gmail and outlook automatic signature wrapper
    is_signature_wrapper = (
        'odoo_signature_wrapper' in el_class or
        # gmail
        'gmail_signature' in el_class or el_id == "Signature" or el.get('data-smartmail')
    )
    is_outlook_auto_message = 'appendonsend' in el_id
    # gmail and outlook reply quote
    is_outlook_reply_quote = 'divRplyFwdMsg' in el_id
    is_gmail_quote = 'gmail_quote' in el_class
    is_quote_wrapper = is_signature_wrapper or is_gmail_quote or is_outlook_reply_quote
    if is_quote_wrapper and el.tag != 't':
        el.set('data-o-mail-quote-container', '1')
        el.set('data-o-mail-quote', '1')

    # outlook reply wrapper is preceded with <hr> and a div containing recipient info
    if is_outlook_reply_quote:
        hr = el.getprevious()
        reply_quote = el.getnext()
        if hr is not None and hr.tag == 'hr':
            hr.set('data-o-mail-quote', '1')
        if reply_quote is not None and reply_quote.tag != 't':
            reply_quote.set('data-o-mail-quote-container', '1')
            reply_quote.set('data-o-mail-quote', '1')

    if is_outlook_auto_message and el.tag != 't':
        if not el.text or not el.text.strip():
            el.set('data-o-mail-quote-container', '1')
            el.set('data-o-mail-quote', '1')

    # html signature (-- <br />blah)
    signature_begin = re.compile(r"((?:(?:^|\n)[-]{2}[\s]?$))")
    if el.text and el.find('br') is not None and re.search(signature_begin, el.text):
        if el.tag != 't':
            el.set('data-o-mail-quote', '1')
        if el.getparent() is not None and el.getparent().tag != 't':
            el.getparent().set('data-o-mail-quote-container', '1')

    # text-based quotes (>, >>) and signatures (-- Signature)
    text_complete_regex = re.compile(r"((?:\n[>]+[^\n\r]*)+|(?:(?:^|\n)[-]{2}[\s]?[\r\n]{1,2}[\s\S]+))")
    if not el.get('data-o-mail-quote'):
        _tag_matching_regex_in_text(text_complete_regex, el, 'span', {'data-o-mail-quote': '1'})

    if el.tag == 'blockquote':
        # remove single node
        el.set('data-o-mail-quote-node', '1')
        el.set('data-o-mail-quote', '1')
    if el.getparent() is not None and not el.getparent().get('data-o-mail-quote-node'):
        if el.getparent().get('data-o-mail-quote') and el.tag != 't':
            el.set('data-o-mail-quote', '1')
        # only quoting the elements following the first quote in the container
        # avoids issues with repeated calls to html_normalize
        elif el.getparent().get('data-o-mail-quote-container'):
            if (first_sibling_quote := el.getparent().find("*[@data-o-mail-quote]")) is not None:
                siblings = el.getparent().getchildren()
                quote_index = siblings.index(first_sibling_quote)
                element_index = siblings.index(el)
                if quote_index < element_index and el.tag != 't':
                    el.set('data-o-mail-quote', '1')
    if el.getprevious() is not None and el.getprevious().get('data-o-mail-quote') and not el.text_content().strip() and el.tag != 't':
        el.set('data-o-mail-quote', '1')


def fromstring(html_, base_url=None, parser=None, **kw):
    """
    This function mimics lxml.html.fromstring. It not only returns the parsed
    element/document but also a flag indicating whether the input is for a
    a single body element or not.

    This tries to minimally parse the chunk of text, without knowing if it
    is a fragment or a document.

    base_url will set the document's base_url attribute (and the tree's docinfo.URL)
    """
    if parser is None:
        parser = html_parser
    if isinstance(html_, Buffer):
        is_full_html = _looks_like_full_html_bytes(bytes(html_))
    else:
        is_full_html = _looks_like_full_html_unicode(html_)
    doc = html.document_fromstring(html_, parser=parser, base_url=base_url, **kw)
    if is_full_html:
        return doc, False
    # otherwise, lets parse it out...
    bodies = doc.findall('body')
    if not bodies:
        bodies = doc.findall('{%s}body' % XHTML_NAMESPACE)
    if bodies:
        body = bodies[0]
        if len(bodies) > 1:
            # Somehow there are multiple bodies, which is bad, but just
            # smash them into one body
            for other_body in bodies[1:]:
                if other_body.text:
                    if len(body):
                        body[-1].tail = (body[-1].tail or '') + other_body.text
                    else:
                        body.text = (body.text or '') + other_body.text
                body.extend(other_body)
                # We'll ignore tail
                # I guess we are ignoring attributes too
                other_body.drop_tree()
    else:
        body = None
    heads = doc.findall('head')
    if not heads:
        heads = doc.findall('{%s}head' % XHTML_NAMESPACE)
    if heads:
        # Well, we have some sort of structure, so lets keep it all
        head = heads[0]
        if len(heads) > 1:
            for other_head in heads[1:]:
                head.extend(other_head)
                # We don't care about text or tail in a head
                other_head.drop_tree()
        return doc, False
    if body is None:
        return doc, False
    if (len(body) == 1 and (not body.text or not body.text.strip())
        and (not body[-1].tail or not body[-1].tail.strip())):
        # The body has just one element, so it was probably a single
        # element passed in
        return body[0], True
    # Now we have a body which represents a bunch of tags which have the
    # content that was passed in.  We will create a fake container, which
    # is the body tag, except <body> implies too much structure.
    if _contains_block_level_tag(body):
        body.tag = 'div'
    else:
        body.tag = 'span'
    return body, False


def html_normalize(src, filter_callback=None, output_method="html"):
    """ Normalize `src` for storage as an html field value.

    The string is parsed as an html tag soup, made valid, then decorated for
    "email quote" detection, and prepared for an optional filtering.
    The filtering step (e.g. sanitization) should be performed by the
    `filter_callback` function (to avoid multiple parsing operations, and
    normalize the result).

    :param src: the html string to normalize
    :param filter_callback: optional callable taking a single `etree._Element`
        document parameter, to be called during normalization in order to
        filter the output document
    :param output_method: defines the output method to pass to `html.tostring`.
        It defaults to 'html', but can also be 'xml' for xhtml output.
    """
    if not src:
        return src

    # html: remove encoding attribute inside tags
    src = re.sub(r'(<[^>]*\s)(encoding=(["\'][^"\']*?["\']|[^\s\n\r>]+)(\s[^>]*|/)?>)', "", src)

    src = src.replace('--!>', '-->')
    src = re.sub(r'(<!-->|<!--->)', '<!-- -->', src)
    # On the specific case of Outlook desktop it adds unnecessary '<o:.*></o:.*>' tags which are parsed
    # in '<p></p>' which may alter the appearance (eg. spacing) of the mail body
    src = re.sub(r'</?o:.*?>', '', src)

    try:
        doc, single_body_element = fromstring(src)
    except etree.ParserError as e:
        # HTML comment only string, whitespace only..
        if 'empty' in str(e):
            return ""
        raise

    # perform quote detection before cleaning and class removal
    for el in doc.iter(tag=etree.Element):
        tag_quote(el)

    doc = html.fromstring(html.tostring(doc, method=output_method))

    if filter_callback:
        doc = filter_callback(doc)

    src = html.tostring(doc, encoding='unicode', method=output_method)

    if not single_body_element and src.startswith('<div>') and src.endswith('</div>'):
        # the <div></div> may come from 2 places
        # 1. the src is parsed as multiple body elements
        #    <div></div> wraps all elements.
        # 2. the src is parsed as not only body elements
        #    <html></html> wraps all elements.
        #    then the Cleaner as the filter_callback which has 'html' in its
        #    'remove_tags' will write <html></html> to <div></div> since it
        #    cannot directly drop the parent-most tag
        src = src[5:-6]

    # html considerations so real html content match database value
    src = src.replace(u'\xa0', u'&nbsp;')

    return src


def html_sanitize(src, silent=True, sanitize_tags=True, sanitize_attributes=False, sanitize_style=False, sanitize_form=True, sanitize_conditional_comments=True, strip_style=False, strip_classes=False, output_method="html"):
    if not src:
        return src

    logger = logging.getLogger(__name__ + '.html_sanitize')

    def sanitize_handler(doc):
        kwargs = {
            'page_structure': True,
            'style': strip_style,              # True = remove style tags/attrs
            'sanitize_style': sanitize_style,  # True = sanitize styling
            'forms': sanitize_form,            # True = remove form tags
            'remove_unknown_tags': False,
            'comments': False,
            'conditional_comments': sanitize_conditional_comments,   # True = remove conditional comments
            'processing_instructions': False
        }
        if sanitize_tags:
            kwargs.update(SANITIZE_TAGS)

        if sanitize_attributes:  # We keep all attributes in order to keep "style"
            if strip_classes:
                current_safe_attrs = safe_attrs - frozenset(['class'])
            else:
                current_safe_attrs = safe_attrs
            kwargs.update({
                'safe_attrs_only': True,
                'safe_attrs': current_safe_attrs,
            })
        else:
            kwargs.update({
                'safe_attrs_only': False,  # keep oe-data attributes + style
                'strip_classes': strip_classes,  # remove classes, even when keeping other attributes
            })

        cleaner = _Cleaner(**kwargs)
        cleaner(doc)
        return doc

    try:
        sanitized = html_normalize(src, filter_callback=sanitize_handler, output_method=output_method)
    except etree.ParserError:
        if not silent:
            raise
        logger.warning(u'ParserError obtained when sanitizing %r', src, exc_info=True)
        sanitized = '<p>ParserError when sanitizing</p>'
    except Exception:
        if not silent:
            raise
        logger.warning(u'unknown error obtained when sanitizing %r', src, exc_info=True)
        sanitized = '<p>Unknown error when sanitizing</p>'

    return markupsafe.Markup(sanitized)


def lxml_remove_element_preserve_tail(element, tail_separator='\n'):
    """Remove an lxml element, mutating its parent tree and preserving its tail."""
    parent_element = element.getparent()
    if parent_element is None:
        return False
    # combine element tail with sibling tail or parent text
    # this is safe as both are escaped xml text and will again be serialized as such
    if element.tail:
        tail = element.tail and element.tail.strip()
        if tail:
            previous_sibling = element.getprevious()
            if previous_sibling is not None:
                previous_sibling.tail = (previous_sibling.tail or '') + tail_separator + tail
            else:
                parent_element.text = (parent_element.text or '') + tail_separator + tail
    parent_element.remove(element)
    return True


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


def append_content_to_html(html, content, plaintext=True, preserve=False, container_tag=None, add_line_breaks=True):
    """ Append extra content at the end of an HTML snippet, trying
        to locate the end of the HTML document (</body>, </html>, or
        EOF), and converting the provided content in html unless ``plaintext``
        is ``False``.

        Content conversion can be done in two ways:

        - wrapping it into a pre (``preserve=True``)
        - use plaintext2html (``preserve=False``, using ``container_tag`` to
          wrap the whole content)

        A side-effect of this method is to coerce all HTML tags to
        lowercase in ``html``, and strip enclosing <html> or <body> tags in
        content if ``plaintext`` is False.

        :param str html: html tagsoup (doesn't have to be XHTML)
        :param str content: extra content to append
        :param bool plaintext: whether content is plaintext and should
            be wrapped in a <pre/> tag.
        :param bool preserve: if content is plaintext, wrap it into a <pre>
            instead of converting it into html
        :param str container_tag: tag to wrap the content into, defaults to `div`.
        :param bool add_line_breaks: content is surrounded by \n, one before and
            one after
        :rtype: markupsafe.Markup
    """
    if plaintext and preserve:
        content = '<pre>%s</pre>' % misc.html_escape(content)
    elif plaintext:
        content = '%s' % plaintext2html(content, container_tag)
    else:
        content = re.sub(r'(?i)(</?(?:html|body|head|!\s*DOCTYPE)[^>]*>)', '', content)
    if add_line_breaks:
        content = '\n%s\n' % content
    # Force all tags to lowercase
    html = re.sub(r'(</?)(\w+)([ >])',
        lambda m: '%s%s%s' % (m[1], m[2].lower(), m[3]), html)
    insert_location = html.find('</body>')
    if insert_location == -1:
        insert_location = html.find('</html>')
    if insert_location == -1:
        return markupsafe.Markup('%s%s' % (html, content))
    return markupsafe.Markup('%s%s%s' % (html[:insert_location], content, html[insert_location:]))


def prepend_html_content(html_body, html_content):
    """Prepend some HTML content at the beginning of an other HTML content."""
    replacement = re.sub(r'(?i)(</?(?:html|body|head|!\s*DOCTYPE)[^>]*>)', '', html_content)
    html_content = markupsafe.Markup(replacement) if isinstance(html_content, markupsafe.Markup) else replacement
    html_content = html_content.strip()

    body_match = re.search(r'<body[^>]*>', html_body) or re.search(r'<html[^>]*>', html_body)
    insert_index = body_match.end() if body_match else 0

    return html_body[:insert_index] + html_content + html_body[insert_index:]
