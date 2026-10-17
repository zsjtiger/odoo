"""The properties fields: the base class of the properties and the checks of the names of their properties."""

from __future__ import annotations

import typing
from operator import attrgetter
from odoo.tools import SQL
from odoo.orm.fields import Field
from odoo.orm.core.utils import regex_alphanumeric

if typing.TYPE_CHECKING:
    from odoo.orm.database.query import FieldSQL, TableSQL


NoneType = type(None)


def check_property_field_value_name(property_name):
    if not (0 < len(property_name) <= 512) or not regex_alphanumeric.match(property_name):
        raise ValueError(f"Wrong property field value name {property_name!r}.")


class Properties(Field):
    """ Field that contains a list of properties (aka "sub-field") based on
    a definition defined on a container. Properties are pseudo-fields, acting
    like Odoo fields but without being independently stored in database.

    This field allows a light customization based on a container record. Used
    for relationships such as <project.project> / <project.task>,... New
    properties can be created on the fly without changing the structure of the
    database.

    The "definition_record" define the field used to find the container of the
    current record. The container must have a :class:`~odoo.fields.PropertiesDefinition`
    field "definition_record_field" that contains the properties definition
    (type of each property, default value)...

    Only the value of each property is stored on the child. When we read the
    properties field, we read the definition on the container and merge it with
    the value of the child. That way the web client has access to the full
    field definition (property type, ...).
    """
    type = 'properties'
    _column_type = ('jsonb', 'jsonb')
    copy = False
    prefetch = False
    write_sequence = 10              # because it must be written after the definition field
    store = True
    readonly = False
    precompute = True
    definition = None
    definition_record = None         # field on the current model that point to the definition record
    definition_record_field = None   # field on the definition record which defined the Properties field definition
    _description_definition_record = property(attrgetter('definition_record'))
    _description_definition_record_field = property(attrgetter('definition_record_field'))
    HTML_SANITIZE_OPTIONS = {
        'sanitize_attributes': True,
        'sanitize_tags': True,
        'sanitize_style': False,
        'sanitize_form': True,
        'sanitize_conditional_comments': True,
        'strip_style': False,
        'strip_classes': False,
    }
    ALLOWED_TYPES = (
        # standard types
        'boolean', 'integer', 'float', 'text', 'char', 'html', 'date', 'datetime', 'monetary', 'signature',
        # relational like types
        'many2one', 'many2many', 'selection', 'tags',
        # UI types
        'separator',
    )
    def _setup_attrs__(self, model_class, name):
        return _setup._setup_attrs__(self, model_class, name)
    def _setup_definition_attrs(self, model_class):
        return _setup._setup_definition_attrs(self, model_class)
    def setup(self, model):
        return _setup.setup(self, model)
    def setup_related(self, model):
        return _setup.setup_related(self, model)
    def convert_to_column(self, value, record, values=None, validate=True):
        return _conversion.convert_to_column(self, value, record, values, validate)
    def convert_to_cache(self, value, records, validate=True):
        return _conversion.convert_to_cache(self, value, records, validate)
    def convert_to_record(self, value, record):
        return _conversion.convert_to_record(self, value, record)
    def convert_to_read(self, value, record, use_display_name=True):
        return _conversion.convert_to_read(self, value, record, use_display_name)
    def convert_to_read_multi(self, values, records, use_display_name=True):
        return _conversion.convert_to_read_multi(self, values, records, use_display_name)
    def convert_to_write(self, value, record):
        return _conversion.convert_to_write(self, value, record)
    def convert_to_export(self, value, record):
        return _conversion.convert_to_export(self, value, record)
    def _get_res_ids_per_model(self, env, values_list):
        return _values._get_res_ids_per_model(self, env, values_list)
    def write(self, records, value):
        return _setup.write(self, records, value)
    def _compute(self, records):
        return _setup._compute(self, records)
    def _add_default_values(self, env, values):
        return _values._add_default_values(self, env, values)
    def _get_properties_definition(self, record):
        return _setup._get_properties_definition(self, record)
    @classmethod
    def _add_display_name(cls, values_list, env, value_keys=('value', 'default')):
        return _values._add_display_name(cls, values_list, env, value_keys)
    @classmethod
    def _remove_display_name(cls, values_list, value_key='value'):
        return _values._remove_display_name(cls, values_list, value_key)
    @staticmethod
    def generate_property_name():
        return _values.generate_property_name()
    @classmethod
    def _add_missing_names(cls, values_list):
        return _values._add_missing_names(cls, values_list)
    @classmethod
    def _parse_json_types(cls, values_list, env, res_ids_per_model):
        return _values._parse_json_types(cls, values_list, env, res_ids_per_model)
    @classmethod
    def _list_to_dict(cls, values_list):
        return _values._list_to_dict(cls, values_list)
    @classmethod
    def _dict_to_list(cls, values_dict, properties_definition):
        return _values._dict_to_list(cls, values_dict, properties_definition)
    def expression_getter(self, field_expr):
        return _query.expression_getter(self, field_expr)
    def filter_function(self, records, field_expr, operator, value):
        return _query.filter_function(self, records, field_expr, operator, value)
    def property_to_sql_raw(self, field_sql: SQL, property_name: str) -> SQL:
        return _query.property_to_sql_raw(self, field_sql, property_name)
    def property_to_sql(self, field_sql: FieldSQL, property_name: str) -> SQL:
        return _query.property_to_sql(self, field_sql, property_name)
    def condition_to_sql(self, table: TableSQL, field_expr: str, operator: str, value) -> SQL:
        return _query.condition_to_sql(self, table, field_expr, operator, value)


# the delegated methods of the properties, at the end: they import this module
from . import setup as _setup, conversion as _conversion, values as _values, query as _query  # noqa: E402
