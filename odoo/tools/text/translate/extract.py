"""Extraction of the translatable terms of the QWeb templates, the formulas and the spreadsheets."""

from __future__ import annotations

import io
import json
import re
import typing
from tokenize import generate_tokens, STRING, NEWLINE, INDENT, DEDENT
from lxml import etree
from odoo.tools.misc import SKIPPED_ELEMENT_TYPES

if typing.TYPE_CHECKING:

    pass

from .html import OWL_TRANSLATED_ATTRS, SKIPPED_ELEMENTS, is_translatable_attrib

def is_meaningful_term(term):
    """ Returns True if the given term is a meaningful translation term that should be exported.

    This is used to filter out terms that are unlikely to be translated, such as purely numeric strings,
    punctuation, or empty strings.
    """
    return bool(term and any(c.isalpha() for c in term.strip()))


def _extract_translatable_qweb_terms(element, callback):
    """ Helper method to walk an etree document representing
        a QWeb template, and call ``callback(term)`` for each
        translatable term that is found in the document.

        :param etree._Element element: root of etree document to extract terms from
        :param Callable callback: a callable in the form ``f(term, source_line)``,
                                  that will be called for each extracted term.
    """
    # not using elementTree.iterparse because we need to skip sub-trees in case
    # the ancestor element had a reason to be skipped
    for el in element:
        if isinstance(el, SKIPPED_ELEMENT_TYPES): continue
        if (el.tag.lower() not in SKIPPED_ELEMENTS
                and "t-js" not in el.attrib
                and not (el.tag == 'attribute' and not is_translatable_attrib(el.get('name'), el))
                and el.get("t-translation", '').strip() != "off"):

            callback(el.text, el.sourceline)
            # heuristic: tags with names starting with an uppercase letter are
            # component nodes
            is_component = el.tag[0].isupper() or "t-component" in el.attrib or "t-set-slot" in el.attrib
            for attr in el.attrib:
                if (not is_component and attr in OWL_TRANSLATED_ATTRS) or (is_component and attr.endswith(".translate")):
                    callback(el.attrib[attr], el.sourceline)
            _extract_translatable_qweb_terms(el, callback)
        callback(el.tail, el.sourceline)


def babel_extract_qweb(fileobj, keywords, comment_tags, options):
    """Babel message extractor for qweb template files.

    :param fileobj: the file-like object the messages should be extracted from
    :param keywords: a list of keywords (i.e. function names) that should
                     be recognized as translation functions
    :param comment_tags: a list of translator tags to search for and
                         include in the results
    :param options: a dictionary of additional options (optional)
    :return: an iterator over ``(lineno, funcname, message, comments)``
             tuples
    :rtype: Iterable
    """
    result = []

    def handle_text(text, lineno):
        text = (text or "").strip()
        if is_meaningful_term(text):
            result.append((lineno, None, text, []))

    tree = etree.parse(fileobj)
    _extract_translatable_qweb_terms(tree.getroot(), handle_text)
    return result


def extract_formula_terms(formula):
    """Extract strings in a spreadsheet formula which are arguments to '_t' functions

        >>> extract_formula_terms('=_t("Hello") + _t("Raoul")')
        ["Hello", "Raoul"]
    """
    tokens = generate_tokens(io.StringIO(formula).readline)
    tokens = (token for token in tokens if token.type not in {NEWLINE, INDENT, DEDENT})
    for t1 in tokens:
        if t1.string != '_t':
            continue
        t2 = next(tokens, None)
        if t2 and t2.string == '(':
            t3 = next(tokens, None)
            t4 = next(tokens, None)
            if t4 and t4.string == ')' and t3 and t3.type == STRING:
                yield t3.string[1:][:-1] # strip leading and trailing quotes


def extract_spreadsheet_terms(fileobj, keywords, comment_tags, options):
    """Babel message extractor for spreadsheet data files.

    :param fileobj: the file-like object the messages should be extracted from
    :param keywords: a list of keywords (i.e. function names) that should
                     be recognized as translation functions
    :param comment_tags: a list of translator tags to search for and
                         include in the results
    :param options: a dictionary of additional options (optional)
    :return: an iterator over ``(lineno, funcname, message, comments)``
             tuples
    """
    terms = set()
    data = json.load(fileobj)
    for sheet in data.get('sheets', []):
        for cell in sheet['cells'].values():
            # 'cell' was an object in versions <saas-18.1
            content = cell if isinstance(cell, str) else cell.get('content', '')
            if content.startswith('='):
                terms.update(extract_formula_terms(content))
            else:
                markdown_link = re.fullmatch(r'\[(.+)\]\(.+\)', content)
                if markdown_link:
                    terms.add(markdown_link[1])
        for figure in sheet['figures']:
            if figure['tag'] == 'chart':
                title = figure['data']['title']
                if isinstance(title, str):
                    terms.add(title)
                elif 'text' in title:
                    terms.add(title['text'])
                if 'axesDesign' in figure['data']:
                    terms.update(
                        axes.get('title', {}).get('text', '') for axes in figure['data']['axesDesign'].values()
                    )
                if 'text' in (baselineDescr := figure['data'].get('baselineDescr', {})):
                    terms.add(baselineDescr['text'])
                if 'text' in (keyDescr := figure['data'].get('keyDescr', {})):
                    terms.add(keyDescr['text'])
            if figure['tag'] == 'carousel':
                title = figure['data'].get('title', {})
                if 'text' in title:
                    terms.add(title['text'])
                items = figure['data'].get('items', [])
                for item in items:
                    if 'title' in item:
                        terms.add(item['title'])
                chartDefinitions = figure['data'].get('chartDefinitions', {}).values()
                for chartDefinition in chartDefinitions:
                    if 'title' in chartDefinition and isinstance(chartDefinition['title'], dict) and 'text' in chartDefinition['title']:
                        terms.add(chartDefinition['title']['text'])

    terms.update(global_filter['label'] for global_filter in data.get('globalFilters', []))
    for odoo_list in data.get('lists', {}).values():
        if not odoo_list.get('translateHeaders', False):
            continue
        columns = odoo_list.get('columns', [])
        for column in columns:
            if isinstance(column, dict) and 'string' in column:
                terms.add(column['string'])
    return (
        (0, None, term, [])
        for term in terms
        if any(x.isalpha() for x in term)
    )
