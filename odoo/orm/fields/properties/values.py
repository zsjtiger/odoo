"""Helpers on the values and the definitions of the properties: the names, the display names, the types and the layout of the values."""

from __future__ import annotations

import contextlib
import copy
import typing
import uuid
from collections import defaultdict
from odoo.exceptions import AccessError, MissingError
from odoo.tools import OrderedSet, is_list_of
from odoo.tools.misc import has_list_types
from odoo.orm.models import BaseModel

if typing.TYPE_CHECKING:
    pass

from .base import NoneType, Properties
from .mapping import Property

def _get_res_ids_per_model(self, env, values_list):
    """Read everything needed in batch for the given records.

    To retrieve relational properties names, or to check their existence,
    we need to do some SQL queries. To reduce the number of queries when we read
    in batch, we prefetch everything needed before calling
    convert_to_record / convert_to_read.

    Return a dict {model: record_ids} that contains
    the existing ids for each needed models.
    """
    # ids per model we need to fetch in batch to put in cache
    ids_per_model = defaultdict(OrderedSet)

    for record_values in values_list:
        for property_definition in record_values:
            comodel = property_definition.get('comodel')
            type_ = property_definition.get('type')
            property_value = property_definition.get('value') or []
            default = property_definition.get('default') or []

            if type_ not in ('many2one', 'many2many') or comodel not in env:
                continue

            if type_ == 'many2one':
                default = [default] if default else []
                property_value = [property_value] if isinstance(property_value, int) else []
            elif not is_list_of(property_value, int):
                property_value = []

            ids_per_model[comodel].update(default)
            ids_per_model[comodel].update(property_value)

    # check existence and pre-fetch in batch
    res_ids_per_model = {}
    for model, ids in ids_per_model.items():
        recs = env[model].browse(ids).exists()
        res_ids_per_model[model] = set(recs.ids)

        for record in recs:
            # read a field to pre-fetch the recordset
            with contextlib.suppress(AccessError):
                record.display_name

    return res_ids_per_model


def _add_default_values(self, env, values):
    """Read the properties definition to add default values.

    Default values are defined on the container in the 'default' key of
    the definition.

    :param env: environment
    :param values: All values that will be written on the record
    :return: Return the default values in the "dict" format
    """
    properties_values = values.get(self.name) or {}

    if isinstance(properties_values, Property):
        properties_values = properties_values._values

    if not values.get(self.definition_record):
        # container is not given in the value, can not find properties definition
        return {}

    container_id = values[self.definition_record]
    if not isinstance(container_id, (int, BaseModel)):
        raise ValueError(f"Wrong container value {container_id!r}")

    if isinstance(container_id, int):
        # retrieve the container record
        current_model = env[self.model_name]
        definition_record_field = current_model._fields[self.definition_record]
        container_model_name = definition_record_field.comodel_name
        container_id = env[container_model_name].sudo().browse(container_id)

    properties_definition = container_id[self.definition_record_field]
    if not (properties_definition or (
        isinstance(properties_values, list)
        and any(d.get('definition_changed') for d in properties_values)
    )):
        # If a parent is set without properties, we might want to change its definition
        # when we create the new record. But if we just set the value without changing
        # the definition, in that case we can just ignored the passed values
        return {}

    assert isinstance(properties_values, (list, dict))
    if isinstance(properties_values, list):
        self._remove_display_name(properties_values)
        properties_list_values = properties_values
    else:
        properties_list_values = self._dict_to_list(properties_values, properties_definition)

    for properties_value in properties_list_values:
        if properties_value.get('value') is None:
            property_name = properties_value.get('name')
            context_key = f"default_{self.name}.{property_name}"
            if property_name and context_key in env.context:
                default = env.context[context_key]
            else:
                default = properties_value.get('default')
            if default:
                properties_value['value'] = default

    return properties_list_values


def _add_display_name(cls, values_list, env, value_keys=('value', 'default')):
    """Add the "display_name" for each many2one / many2many properties.

    Modify in place "values_list".

    :param values_list: List of properties definition and values
    :param env: environment
    """
    for property_definition in values_list:
        property_type = property_definition.get('type')
        property_model = property_definition.get('comodel')
        if not property_model:
            continue

        for value_key in value_keys:
            property_value = property_definition.get(value_key)

            if property_type == 'many2one' and property_value and isinstance(property_value, int):
                try:
                    display_name = env[property_model].browse(property_value).display_name
                    property_definition[value_key] = (property_value, display_name)
                except AccessError:
                    # protect from access error message, show an empty name
                    property_definition[value_key] = (property_value, None)
                except MissingError:
                    property_definition[value_key] = False

            elif property_type == 'many2many' and property_value and is_list_of(property_value, int):
                property_definition[value_key] = []
                records = env[property_model].browse(property_value)
                for record in records:
                    try:
                        property_definition[value_key].append((record.id, record.display_name))
                    except AccessError:
                        property_definition[value_key].append((record.id, None))
                    except MissingError:
                        continue


def _remove_display_name(cls, values_list, value_key='value'):
    """Remove the display name received by the web client for the relational properties.

    Modify in place "values_list".

    - many2one: (35, 'Bob') -> 35
    - many2many: [(35, 'Bob'), (36, 'Alice')] -> [35, 36]

    :param values_list: List of properties definition with properties value
    :param value_key: In which dict key we need to remove the display name
    """
    for property_definition in values_list:
        if not isinstance(property_definition, dict) or not property_definition.get('name'):
            continue

        property_value = property_definition.get(value_key)
        if not property_value:
            continue

        property_type = property_definition.get('type')

        if property_type == 'many2one' and has_list_types(property_value, [int, (str, NoneType)]):
            property_definition[value_key] = property_value[0]

        elif property_type == 'many2many':
            if is_list_of(property_value, (list, tuple)):
                # [(35, 'Admin'), (36, 'Demo')] -> [35, 36]
                property_definition[value_key] = [
                    many2many_value[0]
                    for many2many_value in property_value
                ]


def generate_property_name():
    # keep only the first 64 bits
    return str(uuid.uuid4()).replace('-', '')[:16]


def _add_missing_names(cls, values_list):
    """Generate new properties name if needed.

    Modify in place "values_list".

    :param values_list: List of properties definition with properties value
    """
    for definition in values_list:
        if definition.get('definition_changed') and not definition.get('name'):
            definition['name'] = Properties.generate_property_name()


def _parse_json_types(cls, values_list, env, res_ids_per_model):
    """Parse the value stored in the JSON.

    Check for records existence, if we removed a selection option, ...
    Modify in place "values_list".

    :param values_list: List of properties definition and values
    :param env: environment
    """
    for property_definition in values_list:
        property_value = property_definition.get('value')
        property_type = property_definition.get('type')
        res_model = property_definition.get('comodel')

        if property_type not in cls.ALLOWED_TYPES:
            raise ValueError(f'Wrong property type {property_type!r}')

        if property_value is None:
            continue

        if property_type == 'boolean':
            # E.G. convert zero to False
            property_value = bool(property_value)

        elif property_type in ('char', 'text') and not isinstance(property_value, str):
            property_value = False

        elif property_value and property_type == 'selection':
            # check if the selection option still exists
            options = property_definition.get('selection') or []
            options = {option[0] for option in options if option or ()}  # always length 2
            if property_value not in options:
                # maybe the option has been removed on the container
                property_value = False

        elif property_value and property_type == 'tags':
            # remove all tags that are not defined on the container
            all_tags = {tag[0] for tag in property_definition.get('tags') or ()}
            property_value = [tag for tag in property_value if tag in all_tags]

        elif property_type == 'many2one':
            if not isinstance(property_value, int) \
                    or res_model not in env \
                    or property_value not in res_ids_per_model[res_model]:
                property_value = False

        elif property_type == 'many2many':
            if not is_list_of(property_value, int):
                property_value = []

            elif len(property_value) != len(set(property_value)):
                # remove duplicated value and preserve order
                property_value = list(dict.fromkeys(property_value))

            property_value = [
                id_ for id_ in property_value
                if id_ in res_ids_per_model[res_model]
            ] if res_model in env else []

        elif property_type == 'html':
            # field name should end with `_html` to be legit and sanitized,
            # otherwise do not trust the value and force False
            property_value = property_definition['name'].endswith('_html') and property_value

        property_definition['value'] = property_value


def _list_to_dict(cls, values_list):
    """Convert a list of properties with definition into a dict {name: value}.

    To not repeat data in database, we only store the value of each property on
    the child. The properties definition is stored on the container.

    E.G.
        Input list:
        [{
            'name': '3adf37f3258cfe40',
            'string': 'Color Code',
            'type': 'char',
            'default': 'blue',
            'value': 'red',
        }, {
            'name': 'aa34746a6851ee4e',
            'string': 'Partner',
            'type': 'many2one',
            'comodel': 'test_orm.partner',
            'value': [1337, 'Bob'],
        }]

        Output dict:
        {
            '3adf37f3258cfe40': 'red',
            'aa34746a6851ee4e': 1337,
        }

    :param values_list: List of properties definition and value
    :return: Generate a dict {name: value} from this definitions / values list
    """
    if not is_list_of(values_list, dict):
        raise ValueError(f'Wrong properties value {values_list!r}')

    cls._add_missing_names(values_list)

    dict_value = {}
    for property_definition in values_list:
        property_value = property_definition.get('value')
        property_type = property_definition.get('type')
        property_model = property_definition.get('comodel')
        if property_value is None:
            # Do not store None key
            continue

        if property_type not in ('integer', 'float') or property_value != 0:
            property_value = property_value or False
        if property_type in ('many2one', 'many2many') and property_model and property_value:
            # check that value are correct before storing them in database
            if property_type == 'many2many' and property_value and not is_list_of(property_value, int):
                raise ValueError(f"Wrong many2many value {property_value!r}")

            if property_type == 'many2one' and not isinstance(property_value, int):
                raise ValueError(f"Wrong many2one value {property_value!r}")

        dict_value[property_definition['name']] = property_value

    return dict_value


def _dict_to_list(cls, values_dict, properties_definition):
    """Convert a dict of {property: value} into a list of property definition with values.

    :param values_dict: JSON value coming from the child table
    :param properties_definition: Properties definition coming from the container table
    :return: Merge both value into a list of properties with value
        Ignore every values in the child that is not defined on the container.
    """
    if not is_list_of(properties_definition, dict):
        raise ValueError(f'Wrong properties value {properties_definition!r}')

    values_list = copy.deepcopy(properties_definition)
    for property_definition in values_list:
        if property_definition['name'] in values_dict:
            property_definition['value'] = values_dict[property_definition['name']]
        else:
            property_definition.pop('value', None)
    return values_list
