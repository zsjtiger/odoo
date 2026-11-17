"""Insertion of content in the HTML of a message, as a text or as HTML."""

import re
import markupsafe
from odoo.tools import misc

from .plaintext import plaintext2html

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
