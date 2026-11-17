# Part of Odoo. See LICENSE file for full copyright and licensing details.
"""Validation of the measures, groupbys and search terms of the reporting tools."""

from odoo.tools.misc import submap

from .date_filters import validate_date_groupbys


def compute_report_measures(fields, field_attrs=None, active_measures=None, sum_aggregator_only=False):
    """
    Python equivalent of the JavaScript computeReportMeasures function.

    Args:
        fields (dict): Dictionary of field definitions from fields_get()
        field_attrs (dict): Dictionary of field attributes with visibility info
        active_measures (list): List of active measure field names
        sum_aggregator_only (bool): Only include fields with 'sum' aggregator

    Returns:
        dict: Ordered dictionary of measures with their field definitions
    """
    if field_attrs is None:
        field_attrs = {}
    if active_measures is None:
        active_measures = []

    # Start with the count measure
    measures = {"__count": {"name": "__count", "string": "Count", "type": "integer"}}

    # Process regular fields
    for field_name, field in fields.items():
        if field_name == "id":
            continue

        # Check if field is invisible
        field_attr = field_attrs.get(field_name, {})
        if field_attr.get("isInvisible", False):
            continue

        # Check if field is numeric and has aggregator
        if field.get("type") in ["integer", "float", "monetary"]:
            aggregator = field.get("aggregator")
            if aggregator:
                if sum_aggregator_only and aggregator != "sum":
                    continue
                # Filter field to only include the keys we want
                filtered_field = submap(field, ["type", "aggregator", "name", "string", "sortable"])
                measures[field_name] = filtered_field

    # Add active measures to the measure list
    # This is rarely necessary, but can be useful for functional fields
    # with overridden read_group methods
    for measure in active_measures:
        if measure not in measures and measure in fields:
            # Filter field to only include the keys we want
            filtered_field = submap(fields[measure], ["type", "aggregator", "name", "string", "sortable"])
            measures[measure] = filtered_field

    # Override field strings from field_attrs if provided
    for field_name, field_attr in field_attrs.items():
        if field_attr.get("string") and field_name in measures:
            measures[field_name] = dict(measures[field_name])
            measures[field_name]["string"] = field_attr["string"]

    # Sort measures: Count is always last, others alphabetically by string
    def sort_key(item):
        field_name, field_def = item
        if field_name == "__count":
            return 1, ""  # Count goes last
        return 0, field_def.get("string", "").lower()

    sorted_measures = sorted(measures.items(), key=sort_key)
    return dict(sorted_measures)


def validate_measures(model, measures):
    fields = model.fields_get()
    valid_measures_dict = compute_report_measures(fields, None)
    for measure in measures:
        parts = measure.strip().split()
        if ':' in parts[0]:
            raise ValueError(
                f"Invalid measure syntax '{measure}' for model '{model}'. "
                "Aggregation operators like ':sum' are not supported. "
                "Use '<field_name>' or '<field_name> asc/desc' instead.",
            )
        base_measure = parts[0]
        if base_measure not in valid_measures_dict:
            raise ValueError(
                f"Measure '{base_measure}' is invalid for model '{model}'. "
                f"The base field is not a recognized or aggregatable field.",
            )


def validate_regular_groupbys(model, groupbys):
    if not groupbys:
        return

    model_fields = model.fields_get()
    invalid_groupbys = []
    for groupby in groupbys:
        if len(groupby.split(".")) > 1 or not model_fields.get(groupby, {}).get('groupable'):
            invalid_groupbys.append(groupby)

    if invalid_groupbys:
        raise ValueError(f"The following groupby values are not allowed: {invalid_groupbys}")


def validate_groupbys(model, groupbys):
    """Validate a mixed list of string groupbys and date groupby objects."""
    if not groupbys:
        return

    string_groupbys = []
    date_groupbys = []

    for groupby in groupbys:
        if isinstance(groupby, str):
            string_groupbys.append(groupby)
        elif isinstance(groupby, dict):
            date_groupbys.append(groupby)
        else:
            raise TypeError(f"Invalid groupby type for '{groupby}'. Expected string or dict.")

    validate_regular_groupbys(model, string_groupbys)
    validate_date_groupbys(model, date_groupbys)


def validate_search_terms(search_terms):
    if not search_terms:
        return

    invalid_search_terms = []
    for search_term in search_terms:
        field = search_term["search_field"]
        if "." in field:
            invalid_search_terms.append(search_term)

    if invalid_search_terms:
        raise ValueError(f"Search terms with field chains (containing '.') are not allowed: {invalid_search_terms}")
