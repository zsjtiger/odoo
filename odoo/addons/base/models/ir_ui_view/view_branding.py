"""The branding of the views: the data attributes of the nodes that identify them, and the public assets."""

from __future__ import annotations

import collections
from lxml import etree
from odoo.tools.misc import ConstantMapping
from .helpers import MOVABLE_BRANDING


def _contains_branded(self, node):
    return node.tag == 't'\
        or node.get('t-out') == '0'\
        or 't-call' in node.attrib\
        or any(self.is_node_branded(child) for child in node.iterdescendants())


def _pop_view_branding(self, element):
    distributed_branding = dict(
        (attribute, element.attrib.pop(attribute))
        for attribute in MOVABLE_BRANDING
        if element.get(attribute))
    return distributed_branding


def distribute_branding(self, e, branding=None, parent_xpath='',
                        index_map=ConstantMapping(1)):
    if e.get('t-ignore') or e.tag == 'head':
        # remove any view branding possibly injected by inheritance
        attrs = set(MOVABLE_BRANDING)
        for descendant in e.iterdescendants(tag=etree.Element):
            if not attrs.intersection(descendant.attrib):
                continue
            self._pop_view_branding(descendant)

        # Remove the processing instructions indicating where nodes were
        # removed (see apply_inheritance_specs)
        for descendant in e.iterdescendants(tag=etree.ProcessingInstruction):
            if descendant.target == 'apply-inheritance-specs-node-removal':
                descendant.getparent().remove(descendant)
        return

    node_path = e.get('data-oe-xpath')
    if node_path is None:
        # Handle special case for jump points defined by the magic template
        # <t>$0</t>. No branding is allowed in this case since it points to
        # a generic template.
        if e.get('data-oe-no-branding'):
            e.attrib.pop('data-oe-no-branding')
            return
        node_path = "%s/%s[%d]" % (parent_xpath, e.tag, index_map[e.tag])
    if branding:
        if e.get('t-field'):
            e.set('data-oe-xpath', node_path)
        elif not e.get('data-oe-model'):
            e.attrib.update(branding)
            e.set('data-oe-xpath', node_path)
    if not e.get('data-oe-model'):
        return

    if e.get('t-out'):
        # nodes which fully generate their content and have no reason to
        # be branded because they can not sensibly be edited
        self._pop_view_branding(e)
    elif self._contains_branded(e):
        # if a branded element contains branded elements distribute own
        # branding to children, then just remove branding on current element
        distributed_branding = self._pop_view_branding(e)

        # running index by tag type, for XPath query generation
        indexes = collections.Counter()
        for child in e.iterchildren(etree.Element, etree.ProcessingInstruction):
            if child.get('data-oe-xpath'):
                # injected by view inheritance, skip otherwise
                # generated xpath is incorrect
                self.distribute_branding(child)
            elif child.tag is etree.ProcessingInstruction:
                # If a node is known to have been replaced during
                # applying an inheritance, increment its index to
                # compute an accurate xpath for subsequent nodes
                if child.target == 'apply-inheritance-specs-node-removal':
                    indexes[child.text] += 1
                    e.remove(child)
            else:
                indexes[child.tag] += 1
                self.distribute_branding(
                    child, distributed_branding,
                    parent_xpath=node_path, index_map=indexes)


def is_node_branded(self, node):
    """ Finds out whether a node is branded or qweb-active (bears a
        @data-oe-model or a @t-* *which is not t-field* as t-field does not
        section out views)

        :param node: an etree-compatible element to test
        :type node: etree._Element
        :rtype: boolean
        """
    return any(
        (attr in ('data-oe-model', 'groups') or (attr.startswith('t-')))
        for attr in node.attrib
    ) or (
        node.tag is etree.ProcessingInstruction
        and node.target == 'apply-inheritance-specs-node-removal'
    )


def render_public_asset(self, template, values=None):
    self._get_template_view(template).sudo()._check_view_access()
    return self.sudo()._render_template(template, values)
