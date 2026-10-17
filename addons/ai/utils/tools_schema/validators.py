import re
from types import NoneType

from odoo.exceptions import ValidationError


JSON_SCHEMA_TO_PYTHON_TYPE = {
    'string': str,
    'integer': int,
    'number': (float, int),
    'boolean': bool,
    'array': list,
    'object': dict,
    'null': NoneType,
}


def validate_params_llm_values_with_schema(instance, schema, required_parameters, env):
    for required in required_parameters:
        if required not in instance:
            raise ValidationError(env._("Could you please provide info about '%s' as it is required to process your request", required))

    instance.update({param: None for param in schema if param not in instance})

    for name, value in instance.items():
        if name not in schema:
            raise ValidationError(env._("Missing definition for %(name)s", name=name))
        if name not in required_parameters and value is None:
            continue
        instance[name] = _validate_param(name, value, schema[name], env)

    return instance


def _validate_param(name, value, param_schema, env):
    """Validate one value against its schema and return the value to use (possibly adjusted)."""
    # Handle anyOf schemas - try each schema option until one succeeds
    if 'anyOf' in param_schema:
        for schema_option in param_schema['anyOf']:
            try:
                # Extract the validated value from the result dict
                return validate_params_llm_values_with_schema({name: value}, {name: schema_option}, [name], env)[name]
            except ValidationError:
                continue
        raise ValidationError(env._(
            "The value of parameter '%(name)s' doesn't match any of the expected schemas.",
            name=name,
        ))

    param_type = param_schema['type']
    invalid_type = (
        param_type not in JSON_SCHEMA_TO_PYTHON_TYPE
        or not isinstance(value, JSON_SCHEMA_TO_PYTHON_TYPE[param_type])
        or (param_type in ('integer', 'number') and isinstance(value, bool))
    )
    if invalid_type:
        raise ValidationError(env._(
            "The type of the parameter '%(name)s' is incorrect. It should be '%(expected_param_type)s'.",
            name=name,
            expected_param_type=param_type,
        ))

    minimum = param_schema.get('minimum')
    if param_type in ('integer', 'number') and minimum is not None and value < minimum:
        raise ValidationError(env._(
            "The value of the parameter '%(name)s' must be at least %(minimum)s.",
            name=name,
            minimum=minimum,
        ))

    expected_pattern = param_type == 'string' and param_schema.get('pattern')
    if expected_pattern and not re.fullmatch(expected_pattern, value):
        raise ValidationError(env._(
            "The value '%(value)s' of the parameter '%(name)s' doesn't match the expected pattern '%(expected_pattern)s'.",
            value=value,
            name=name,
            expected_pattern=expected_pattern,
        ))

    if (enum := param_schema.get('enum')) and value not in enum:
        raise ValidationError(env._("Wrong value %(value)s, should be in: %(enum)s", value=value, enum=", ".join(map(str, enum))))

    max_length = param_type == 'string' and param_schema.get('maxLength')
    if isinstance(value, str) and max_length and len(value) > max_length:
        # As of July 31, Gemini does not respect the `maxLength` JSON schema
        # (while OpenAI does), so we manually truncate the arguments if needed
        value = value[:max_length] + "..."

    if param_type == 'object':
        return validate_params_llm_values_with_schema(
            value,
            param_schema.get('properties', {}),
            param_schema.get('required', []),
            env,
        )

    if param_type == 'array':
        item_name = f"{name}'s item"
        for item_value in value:
            validate_params_llm_values_with_schema(
                {item_name: item_value},
                {item_name: param_schema['items']},
                [item_name],
                env,
            )
    return value
