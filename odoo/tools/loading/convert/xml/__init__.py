# Part of Odoo. See LICENSE file for full copyright and licensing details.
# ruff: noqa: F401
"""The import of the XML data files: the documents, the records and the evaluation of the values. The names are re-exported here."""

from .base import convert_xml_import, xml_import
from .values import _eval_xml, _fix_multiple_roots
