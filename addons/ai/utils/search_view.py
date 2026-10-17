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

    # Parse XML
    tree = etree.fromstring(search_view_arch)

    sections = []

    # 1. Searchable fields
    searchable_fields = []
    for field in tree.xpath(".//field[@name and not(@invisible='1') and not(ancestor::group)]"):
        field_info = {"name": field.get("name")}
        if field.get("string"):
            field_info["string"] = field.get("string")
        if field.get("filter_domain"):
            field_info["filter_domain"] = field.get("filter_domain")
        if field.get("operator"):
            field_info["operator"] = field.get("operator")
        searchable_fields.append(field_info)

    if searchable_fields:
        lines = ["Searchable fields:"]
        for field in searchable_fields:
            field_parts = [field["name"]]
            if "string" in field:
                field_parts.append(field["string"])
            if "filter_domain" in field:
                field_parts.append(f'filter_domain="{field["filter_domain"]}"')
            if "operator" in field:
                field_parts.append(f"operator={field['operator']}")
            lines.append(f"  - {', '.join(field_parts)}")
        sections.append("\n".join(lines))

    # 2. Filters grouped by separators (including date filters)
    filter_groups = []
    current_group = []

    for elem in tree:
        if elem.tag == "separator":
            if current_group:
                filter_groups.append(current_group)
                current_group = []
        elif elem.tag == "filter" and elem.get("name") and elem.get("invisible") != "1":
            if elem.getparent().tag != "group":
                filter_info = {"name": elem.get("name")}
                if elem.get("string"):
                    filter_info["string"] = elem.get("string")

                # Check if this is a date filter
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
                else:
                    # Regular filter
                    if elem.get("domain"):
                        filter_info["domain"] = elem.get("domain")

                current_group.append(filter_info)

    if current_group:
        filter_groups.append(current_group)

    if filter_groups:
        lines = ["Filters:"]
        for group_idx, group in enumerate(filter_groups, 1):
            lines.append(f"  [Group {group_idx}]")
            for filter_item in group:
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

                    lines.append(f"    - {', '.join(parts)}")
                else:
                    # Regular filter
                    filter_parts = [filter_item["name"]]
                    if "string" in filter_item:
                        filter_parts.append(filter_item["string"])
                    if "domain" in filter_item:
                        filter_parts.append(f'domain="{filter_item["domain"]}"')
                    lines.append(f"    - {', '.join(filter_parts)}")
        sections.append("\n".join(lines))

    # 3. Groupbys (regular and date)
    regular_groupbys = []
    date_groupbys = []

    def is_date_groupby(value):
        if ":" in value:
            return True
        return model_fields.get(value, {}).get("type") in ["date", "datetime"]

    for group in tree.xpath(".//group"):
        for filter_elem in group.xpath(".//filter[@name and not(@invisible='1')]"):
            if filter_elem.get("context") and "group_by" in filter_elem.get("context"):
                context_str = filter_elem.get("context")
                context_dict = literal_eval(context_str)
                raw_group_by = context_dict.get("group_by")
                group_bys = [raw_group_by] if isinstance(raw_group_by, str) else raw_group_by or []

                for group_by in group_bys:
                    groupby_info = {
                        "name": filter_elem.get("name"),
                        "string": filter_elem.get("string") or ""
                    }

                    if is_date_groupby(group_by):
                        field_name, *interval = group_by.split(":", 1)
                        interval = interval[0] if interval else "month"
                        groupby_info["field_name"] = field_name
                        groupby_info["default_interval"] = interval
                        date_groupbys.append(groupby_info)
                    else:
                        groupby_info["field_name"] = group_by
                        regular_groupbys.append(groupby_info)

    if regular_groupbys:
        lines = ["Groupbys:"]
        for groupby in regular_groupbys:
            parts = [groupby["field_name"]]
            if groupby["string"]:
                parts.append(groupby["string"])
            lines.append(f"  - {', '.join(parts)}")
        sections.append("\n".join(lines))

    if date_groupbys:
        lines = ["Date groupbys:"]
        for groupby in date_groupbys:
            parts = [groupby["field_name"]]
            if groupby["string"]:
                parts.append(groupby["string"])
            parts.append(f"default_interval={groupby['default_interval']}")
            lines.append(f"  - {', '.join(parts)}")
        sections.append("\n".join(lines))

    result = "\n\n".join(sections)
    return result
