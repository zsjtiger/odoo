"""Translation of the XML and HTML fields: the terms, the attributes and the format strings."""

from __future__ import annotations

import logging
import re
import typing
from lxml import etree, html
from odoo.exceptions import UserError
from odoo.tools.misc import SKIPPED_ELEMENT_TYPES

if typing.TYPE_CHECKING:

    pass

from .base import _, get_text_content, is_text

_logger = logging.getLogger('odoo.tools.text.translate')


SKIPPED_ELEMENTS = ('script', 'style', 'title')


TRANSLATED_ELEMENTS = {
    'abbr', 'b', 'bdi', 'bdo', 'br', 'cite', 'code', 'data', 'del', 'dfn', 'em',
    'font', 'i', 'ins', 'kbd', 'keygen', 'mark', 'math', 'meter', 'output',
    'progress', 'q', 'ruby', 's', 'samp', 'small', 'span', 'strong', 'sub',
    'sup', 'time', 'u', 'var', 'wbr', 'text',
}


TRANSLATED_ATTRS = {
    'string', 'add-label', 'help', 'sum', 'avg', 'confirm', 'placeholder', 'alt', 'title', 'aria-label',
    'aria-keyshortcuts', 'aria-placeholder', 'aria-roledescription', 'aria-valuetext',
    'value_label', 'data-tooltip', 'label', 'confirm-label', 'cancel-label', 'confirm-title',
}


TRANSLATED_ATTRS.update({f't-attf-{attr}' for attr in TRANSLATED_ATTRS})


FIELD_TRANSLATE = {
    None: False,
    'standard': True,
}


def is_translatable_attrib(key, node):
    if not key:
        return False
    if 't-call' not in node.attrib and key in TRANSLATED_ATTRS:
        return True
    return key.endswith('.translate')


def is_translatable_attrib_value(node):
    # check if the value attribute of a node must be translated
    classes = node.attrib.get('class', '').split(' ')
    return (
        (node.tag == 'input' and node.attrib.get('type', 'text') == 'text')
        and 'datetimepicker-input' not in classes
        or (node.tag == 'input' and node.attrib.get('type') == 'hidden')
        and 'o_translatable_input_hidden' in classes
    )


def is_translatable_attrib_text(node):
    return node.tag == 'field' and node.attrib.get('widget', '') == 'url'


OWL_TRANSLATED_ATTRS = {
    "alt",
    "aria-label",
    "aria-placeholder",
    "aria-roledescription",
    "aria-valuetext",
    "data-tooltip",
    "label",
    "placeholder",
    "title",
}


avoid_pattern = re.compile(r"\s*<!DOCTYPE", re.IGNORECASE | re.MULTILINE | re.UNICODE)


space_pattern = re.compile(r"[\s\uFEFF]*")  # web_editor uses \uFEFF as ZWNBSP


FORMAT_REGEX = re.compile(r'(?:#\{(.+?)\})|(?:\{\{(.+?)\}\})')


def translate_format_string_expression(term, callback):
    expressions = {}
    def add(exp_py):
        index = len(expressions)
        expressions[str(index)] = exp_py
        return '{{%s}}' % index
    term_without_py = FORMAT_REGEX.sub(lambda g: add(g.group(0)), term)
    translated_value = callback(term_without_py)
    if translated_value:
        return FORMAT_REGEX.sub(lambda g: expressions.get(g.group(0)[2:-2], 'None'), translated_value)


def translate_xml_node(node, callback, parse, serialize):
    """ Return the translation of the given XML/HTML node.

        :param node:
        :param callback: callback(text) returns translated text or None
        :param parse: parse(text) returns a node (text is unicode)
        :param serialize: serialize(node) returns unicode text
    """

    def nonspace(text):
        """ Return whether ``text`` is a string with non-space characters. """
        return bool(text) and not space_pattern.fullmatch(text)

    def is_force_inline(node):
        """ Return whether ``node`` is marked as it should be translated as
            one term.
        """
        return "o_translate_inline" in node.attrib.get("class", "").split()

    def translatable(node, force_inline=False):
        """ Return whether the given node can be translated as a whole. """
        # Some specific nodes (e.g., text highlights) have an auto-updated DOM
        # structure that makes them impossible to translate.
        # The introduction of a translation `<span>` in the middle of their
        # hierarchy breaks their functionalities. We need to force them to be
        # translated as a whole using the `o_translate_inline` class.
        force_inline = force_inline or is_force_inline(node)
        return (
            (force_inline or node.tag in TRANSLATED_ELEMENTS)
            # Nodes with directives are not translatable. Directives usually
            # start with `t-`, but this prefix is optional for `groups` (see
            # `_compile_directive_groups` which reads `t-groups` and `groups`)
            and not any(key.startswith("t-") or key == 'groups' or key.endswith(".translate") for key in node.attrib)
            and all(translatable(child, force_inline) for child in node)
        )

    def hastext(node, pos=0, force_inline=False):
        """ Return whether the given node contains some text to translate at the
            given child node position.  The text may be before the child node,
            inside it, or after it.
        """
        force_inline = force_inline or is_force_inline(node)
        return (
            # there is some text before node[pos]
            nonspace(node[pos-1].tail if pos else node.text)
            or (
                pos < len(node)
                and translatable(node[pos], force_inline)
                and (
                    any(  # attribute to translate
                        val and (
                            is_translatable_attrib(key, node) or
                            (key == 'value' and is_translatable_attrib_value(node[pos])) or
                            (key == 'text' and is_translatable_attrib_text(node[pos]))
                        )
                        for key, val in node[pos].attrib.items()
                    )
                    # node[pos] contains some text to translate
                    or hastext(node[pos], 0, force_inline)
                    # node[pos] has no text, but there is some text after it
                    or hastext(node, pos + 1, force_inline)
                )
            )
        )

    def process(node):
        """ Translate the given node. """
        if (
            isinstance(node, SKIPPED_ELEMENT_TYPES)
            or node.tag in SKIPPED_ELEMENTS
            or node.get('t-translation', "").strip() == "off"
            or node.tag == 'attribute' and node.get('name') not in ('value', 'text') and not is_translatable_attrib(node.get('name'), node)
            or node.getparent() is None and avoid_pattern.match(node.text or "")
        ):
            return

        pos = 0
        while True:
            # check for some text to translate at the given position
            if hastext(node, pos):
                # move all translatable children nodes from the given position
                # into a <div> element
                div = etree.Element('div')
                div.text = (node[pos-1].tail if pos else node.text) or ''
                while pos < len(node) and translatable(node[pos], is_force_inline(node)):
                    div.append(node[pos])

                # translate the content of the <div> element as a whole
                content = serialize(div)[5:-6]
                original = content.strip()
                translated = callback(original)
                if translated:
                    result = content.replace(original, translated)
                    # <div/> is used to auto fix crapy result
                    result_elem = parse_html(f"<div>{result}</div>")
                    # change the tag to <span/> which is one of TRANSLATED_ELEMENTS
                    # so that 'result_elem' can be checked by translatable and hastext
                    result_elem.tag = 'span'
                    if translatable(result_elem) and hastext(result_elem):
                        if node.tag.lower() == 'option' and len(result_elem) and result_elem[0].get('data-oe-translation-source-sha'):
                            # In 'edit_translations' context, a <span> wrapper
                            # is put in 'result_elem' to let the user translate
                            # fields in the frontend.
                            # But <span> can't be inside an <option> element,
                            # so we put it in an attribute instead.
                            # In this context, we can skip replacing the node
                            # content.
                            node.set('data-oe-translation-span-wrapper', etree.tostring(result_elem[0]))
                        else:
                            div = result_elem
                            if pos:
                                node[pos - 1].tail = div.text
                            else:
                                node.text = div.text

                # move the content of the <div> element back inside node
                while len(div) > 0:
                    node.insert(pos, div[0])
                    pos += 1

            if pos >= len(node):
                break

            # node[pos] is not translatable as a whole, process it recursively
            process(node[pos])
            pos += 1

        # translate the attributes of the node
        for key, val in node.attrib.items():
            if nonspace(val):
                if (
                    is_translatable_attrib(key, node) or
                    (key == 'value' and is_translatable_attrib_value(node)) or
                    (key == 'text' and is_translatable_attrib_text(node))
                ):
                    if key.startswith('t-'):
                        value = translate_format_string_expression(val.strip(), callback)
                    else:
                        value = callback(val.strip())
                    node.set(key, value or val)

    process(node)

    return node


def parse_xml(text):
    return etree.fromstring(text)


def serialize_xml(node):
    return etree.tostring(node, method='xml', encoding='unicode')


MODIFIER_ATTRS = {"invisible", "readonly", "required", "column_invisible", "attrs"}


def xml_term_adapter(term_en):
    """
    Returns an `adapter(term)` function that will ensure the modifiers are copied
    from the base `term_en` to the translated `term` when the XML structure of
    both terms match. `term_en` and any input `term` to the adapter must be valid
    XML terms. Using the adapter only makes sense if `term_en` contains some tags
    from TRANSLATED_ELEMENTS.
    """
    orig_node = parse_xml(f"<div>{term_en}</div>")

    def same_struct_iter(left, right):
        if left.tag != right.tag or len(left) != len(right):
            raise ValueError("Non matching struct")
        yield left, right
        left_iter = left.iterchildren()
        right_iter = right.iterchildren()
        for lc, rc in zip(left_iter, right_iter):
            yield from same_struct_iter(lc, rc)

    def adapter(term):
        new_node = parse_xml(f"<div>{term}</div>")
        try:
            for orig_n, new_n in same_struct_iter(orig_node, new_node):
                removed_attrs = [k for k in new_n.attrib if k in MODIFIER_ATTRS and k not in orig_n.attrib]
                for k in removed_attrs:
                    del new_n.attrib[k]
                keep_attrs = {k: v for k, v in orig_n.attrib.items()}
                new_n.attrib.update(keep_attrs)
        except ValueError:  # non-matching structure
            return None

        # remove tags <div> and </div> from result
        return serialize_xml(new_node)[5:-6]

    return adapter


_HTML_PARSER = etree.HTMLParser(encoding='utf8')


def parse_html(text):
    try:
        parse = html.fragment_fromstring(text, parser=_HTML_PARSER)
    except (etree.ParserError, TypeError) as e:
        raise UserError(_("Error while parsing view:\n\n%s") % e) from e
    return parse


def serialize_html(node):
    return etree.tostring(node, method='html', encoding='unicode')


def xml_translate(callback, value):
    """ Translate an XML value (string), using `callback` for translating text
        appearing in `value`.
    """
    if not value:
        return value

    try:
        root = parse_xml(value)
        result = translate_xml_node(root, callback, parse_xml, serialize_xml)
        return serialize_xml(result)
    except etree.ParseError:
        # fallback for translated terms: use an HTML parser and wrap the term
        root = parse_html(u"<div>%s</div>" % value)
        result = translate_xml_node(root, callback, parse_xml, serialize_xml)
        # remove tags <div> and </div> from result
        return serialize_xml(result)[5:-6]


def xml_term_converter(value):
    """ Convert the HTML fragment ``value`` to XML if necessary
    """
    # wrap value inside a div and parse it as HTML
    div = f"<div>{value}</div>"
    root = etree.fromstring(div, etree.HTMLParser())
    # root is html > body > div
    # serialize div as XML and discard surrounding tags
    return etree.tostring(root[0][0], encoding='unicode')[5:-6]


def html_translate(callback, value):
    """ Translate an HTML value (string), using `callback` for translating text
        appearing in `value`.
    """
    if not value:
        return value

    try:
        # value may be some HTML fragment, wrap it into a div
        root = parse_html("<div>%s</div>" % value)
        result = translate_xml_node(root, callback, parse_html, serialize_html)
        # remove tags <div> and </div> from result
        value = serialize_html(result)[5:-6].replace('\xa0', '&nbsp;')
    except ValueError:
        _logger.exception("Cannot translate malformed HTML, using source value instead")

    return value


def html_term_converter(value):
    """ Convert the HTML fragment ``value`` to XML if necessary
    """
    # wrap value inside a div and parse it as HTML
    div = f"<div>{value}</div>"
    root = etree.fromstring(div, etree.HTMLParser())
    # root is html > body > div
    # serialize div as HTML and discard surrounding tags
    return etree.tostring(root[0][0], encoding='unicode', method='html')[5:-6]


xml_translate.get_text_content = get_text_content


html_translate.get_text_content = get_text_content


xml_translate.term_converter = xml_term_converter


html_translate.term_converter = html_term_converter


xml_translate.is_text = is_text


html_translate.is_text = is_text


xml_translate.term_adapter = xml_term_adapter


FIELD_TRANSLATE['html_translate'] = html_translate


FIELD_TRANSLATE['xml_translate'] = xml_translate
