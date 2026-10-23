# Part of Odoo. See LICENSE file for full copyright and licensing details.
"""The default lxml parsers: they are configured when the package is imported."""

from __future__ import annotations
import typing
from lxml import etree, objectify

if typing.TYPE_CHECKING:
    pass


SKIPPED_ELEMENT_TYPES = (etree._Comment, etree._ProcessingInstruction, etree.CommentBase, etree.PIBase, etree._Entity)


etree.set_default_parser(etree.XMLParser(resolve_entities=False))


default_parser = etree.XMLParser(resolve_entities=False, remove_blank_text=True)


default_parser.set_element_class_lookup(objectify.ObjectifyElementClassLookup())


objectify.set_default_parser(default_parser)
