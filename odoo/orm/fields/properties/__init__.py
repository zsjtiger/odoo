# Part of Odoo. See LICENSE file for full copyright and licensing details.
# ruff: noqa: F401
"""The properties fields: the base, the setup, the conversions, the values, the queries, and the mapping and the definition. The names are re-exported here."""

from .base import check_property_field_value_name, NoneType, Properties
from .query import SQLWithProperty
from .mapping import Property
from .definition import PropertiesDefinition
