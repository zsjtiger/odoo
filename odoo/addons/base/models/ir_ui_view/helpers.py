"""The helpers of the views: the logger, the constants, the XML helpers and the XPath functions."""

from __future__ import annotations

import logging
import re
from lxml import etree
from odoo.tools.loading.convert import _fix_multiple_roots
from odoo.tools.text.translate import TRANSLATED_ATTRS


_logger = logging.getLogger('odoo.addons.base.models.ir_ui_view')


MOVABLE_BRANDING = ['data-oe-model', 'data-oe-id', 'data-oe-field', 'data-oe-xpath', 'data-oe-source-id']


VIEW_MODIFIERS = ('column_invisible', 'invisible', 'readonly', 'required')


QUARTER_PERIODS = {'first_quarter', 'second_quarter', 'third_quarter', 'fourth_quarter'}


RELATIVE_PERIODS = {'today', 'this_week', 'this_month', 'this_quarter', 'this_year'}


COMP_REGEX = r'(^|[^\w])\s*__comp__\s*([^\w]|$)'


ref_re = re.compile(r"""
# first match 'form_view_ref' key, backrefs are used to handle single or
# double quoting of the value
(['"])(?P<view_type>\w+_view_ref)\1
# colon separator (with optional spaces around)
\s*:\s*
# open quote for value
(['"])
(?P<view_id>
    # we'll just match stuff which is normally part of an xid:
    # word and "." characters
    [.\w]+
)
# close with same quote as opening
\3
""", re.VERBOSE)


def att_names(name):
    yield name
    yield f"t-att-{name}"
    yield f"t-attf-{name}"


def _hasclass(context, *cls):
    """ Checks if the context node has all the classes passed as arguments
    """
    node_classes = set(context.context_node.attrib.get('class', '').split())
    return node_classes.issuperset(cls)


def get_view_arch_from_file(filepath, xmlid):
    module, view_id = xmlid.split('.')

    xpath = f"//*[@id='{xmlid}' or @id='{view_id}']"
    # when view is created from model with inheritS of ir_ui_view, the
    # xmlid has been suffixed by '_ir_ui_view'. We need to also search
    # for views without this prefix.
    if view_id.endswith('_ir_ui_view'):
        # len('_ir_ui_view') == 11
        xpath = xpath[:-1] + f" or @id='{xmlid[:-11]}' or @id='{view_id[:-11]}']"

    document = etree.parse(filepath)
    for node in document.xpath(xpath):
        if node.tag == 'record':
            field_arch = node.find('field[@name="arch"]')
            if field_arch is not None:
                _fix_multiple_roots(field_arch)
                inner = ''.join(
                    etree.tostring(child, encoding='unicode')
                    for child in field_arch.iterchildren()
                )
                return field_arch.text + inner

            field_view = node.find('field[@name="view_id"]')
            if field_view is not None:
                ref_module, _, ref_view_id = field_view.attrib.get('ref').rpartition('.')
                ref_xmlid = f'{ref_module or module}.{ref_view_id}'
                return get_view_arch_from_file(filepath, ref_xmlid)

            return None

        elif node.tag == 'template':
            # The following dom operations has been copied from convert.py's _tag_template()
            if not node.get('inherit_id'):
                node.set('t-name', xmlid)
                node.tag = 't'
            else:
                node.tag = 'data'
            node.attrib.pop('id', None)
            return etree.tostring(node, encoding='unicode')

    _logger.warning("Could not find view arch definition in file '%s' for xmlid '%s'", filepath, xmlid)
    return None


xpath_utils = etree.FunctionNamespace(None)


xpath_utils['hasclass'] = _hasclass


TRANSLATED_ATTRS_RE = re.compile(r"@(%s)\b" % "|".join(TRANSLATED_ATTRS))


WRONGCLASS = re.compile(r"(@class\s*=|=\s*@class|contains\(@class)")
