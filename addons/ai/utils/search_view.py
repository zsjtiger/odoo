# Part of Odoo. See LICENSE file for full copyright and licensing details.
"""Search view introspection: the filters and groupbys a search view offers."""
from ast import literal_eval

from lxml import etree


def get_search_view(model, action):
    if action.type != "ir.actions.act_window":
        return None

    return model.get_views(
        [[action.search_view_id.id, "search"]],
        options={"action_id": action.id, "toolbar": False},
    )["views"]["search"]


def serialize_search_view_info(model_fields, search_view_arch):
    """Serialize search view information into a structured text format for AI consumption.

    Returns a text-based representation containing:
    - Searchable fields
    - Filters (grouped by separators)
    - Regular field groupbys
    - Date field groupbys
    """
    if not search_view_arch:
        return ""

    tree = etree.fromstring(search_view_arch)
    regular_groupbys, date_groupbys = _collect_groupbys(tree, model_fields)
    sections = [
        _format_searchable_fields(tree),
        _format_filters(_filter_groups(tree)),
        _format_groupbys("Groupbys:", regular_groupbys),
        _format_groupbys("Date groupbys:", date_groupbys, with_interval=True),
    ]
    return "\n\n".join(section for section in sections if section)


def _format_searchable_fields(tree):
    searchable_fields = []
    for field in tree.xpath(".//field[@name and not(@invisible='1') and not(ancestor::group)]"):
        field_parts = [field.get("name")]
        if field.get("string"):
            field_parts.append(field.get("string"))
        if field.get("filter_domain"):
            field_parts.append(f'filter_domain="{field.get("filter_domain")}"')
        if field.get("operator"):
            field_parts.append(f"operator={field.get('operator')}")
        searchable_fields.append(f"  - {', '.join(field_parts)}")
    if not searchable_fields:
        return ""
    return "\n".join(["Searchable fields:", *searchable_fields])


def _filter_groups(tree):
    """Filters at the top level of the view, split into groups by separators."""
    filter_groups = []
    current_group = []
    for elem in tree:
        if elem.tag == "separator":
            if current_group:
                filter_groups.append(current_group)
                current_group = []
        elif elem.tag == "filter" and elem.get("name") and elem.get("invisible") != "1":
            if elem.getparent().tag != "group":
                current_group.append(_filter_info(elem))
    if current_group:
        filter_groups.append(current_group)
    return filter_groups


def _filter_info(elem):
    filter_info = {"name": elem.get("name")}
    if elem.get("string"):
        filter_info["string"] = elem.get("string")
    if elem.get("date"):
        filter_info["is_date_filter"] = True
        filter_info["field_name"] = elem.get("date")
        filter_info["start_year"] = elem.get("start_year", "-2")
        filter_info["end_year"] = elem.get("end_year", "0")
        filter_info["start_month"] = elem.get("start_month", "-2")
        filter_info["end_month"] = elem.get("end_month", "0")
        # Extract custom options (prefix with "custom_" as done by client)
        child_filters = elem.xpath("./filter[@name]")
        if child_filters:
            filter_info["options"] = [
                {"name": f"custom_{child.get('name')}", "string": child.get("string")}
                for child in child_filters
            ]
    elif elem.get("domain"):
        filter_info["domain"] = elem.get("domain")
    return filter_info


def _format_filters(filter_groups):
    if not filter_groups:
        return ""
    lines = ["Filters:"]
    for group_idx, group in enumerate(filter_groups, 1):
        lines.append(f"  [Group {group_idx}]")
        lines.extend(f"    - {_format_filter_item(item)}" for item in group)
    return "\n".join(lines)


def _format_filter_item(filter_item):
    if filter_item.get("is_date_filter"):
        # Date filter: [DATE FILTER] field_name, label, year_range, month_range, options
        parts = [f"[DATE FILTER] {filter_item['field_name']}"]
        if "string" in filter_item:
            parts.append(filter_item["string"])
        parts.append(f'year_range=[{filter_item["start_year"]} to {filter_item["end_year"]}]')
        parts.append(f'month_range=[{filter_item["start_month"]} to {filter_item["end_month"]}]')
        if "options" in filter_item:
            option_strs = [f'{opt["name"]}="{opt["string"]}"' for opt in filter_item["options"]]
            parts.append(f'options=[{", ".join(option_strs)}]')
        return ', '.join(parts)
    filter_parts = [filter_item["name"]]
    if "string" in filter_item:
        filter_parts.append(filter_item["string"])
    if "domain" in filter_item:
        filter_parts.append(f'domain="{filter_item["domain"]}"')
    return ', '.join(filter_parts)


def _collect_groupbys(tree, model_fields):
    """Return the (regular, date) groupbys offered by the view's filters."""
    regular_groupbys = []
    date_groupbys = []

    def is_date_groupby(value):
        if ":" in value:
            return True
        return model_fields.get(value, {}).get("type") in ["date", "datetime"]

    for group in tree.xpath(".//group"):
        for filter_elem in group.xpath(".//filter[@name and not(@invisible='1')]"):
            if filter_elem.get("context") and "group_by" in filter_elem.get("context"):
                context_dict = literal_eval(filter_elem.get("context"))
                raw_group_by = context_dict.get("group_by")
                group_bys = [raw_group_by] if isinstance(raw_group_by, str) else raw_group_by or []
                for group_by in group_bys:
                    groupby_info = {
                        "name": filter_elem.get("name"),
                        "string": filter_elem.get("string") or "",
                    }
                    if is_date_groupby(group_by):
                        field_name, *interval = group_by.split(":", 1)
                        groupby_info["field_name"] = field_name
                        groupby_info["default_interval"] = interval[0] if interval else "month"
                        date_groupbys.append(groupby_info)
                    else:
                        groupby_info["field_name"] = group_by
                        regular_groupbys.append(groupby_info)
    return regular_groupbys, date_groupbys


def _format_groupbys(title, groupbys, with_interval=False):
    if not groupbys:
        return ""
    lines = [title]
    for groupby in groupbys:
        parts = [groupby["field_name"]]
        if groupby["string"]:
            parts.append(groupby["string"])
        if with_interval:
            parts.append(f"default_interval={groupby['default_interval']}")
        lines.append(f"  - {', '.join(parts)}")
    return "\n".join(lines)
