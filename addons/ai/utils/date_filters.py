# Part of Odoo. See LICENSE file for full copyright and licensing details.
"""Date filters of the reporting tools: validation and computation of relative dates."""
import calendar
import re
from datetime import datetime, timedelta, UTC
from lxml import etree
from zoneinfo import ZoneInfo

from odoo.tools import DEFAULT_SERVER_DATE_FORMAT, DEFAULT_SERVER_DATETIME_FORMAT

from .search_view import get_search_view


VALID_INTERVALS = ['day', 'week', 'month', 'quarter', 'year']


VALID_QUARTERS = ['first_quarter', 'second_quarter', 'third_quarter', 'fourth_quarter']


QUARTER_MONTHS = {
    1: (1, 2, 3),  # Q1: Jan-Mar
    2: (4, 5, 6),  # Q2: Apr-Jun
    3: (7, 8, 9),  # Q3: Jul-Sep
    4: (10, 11, 12),  # Q4: Oct-Dec
}


MAX_OFFSET = 100


MIN_OFFSET = -100


BOUNDARY_TIME_RESETS = {
    "start": {
        'minute': {'second': 0, 'microsecond': 0},
        'hour': {'minute': 0, 'second': 0, 'microsecond': 0},
        'day': {'hour': 0, 'minute': 0, 'second': 0, 'microsecond': 0},
    },
    "end": {
        'minute': {'second': 59, 'microsecond': 999999},
        'hour': {'minute': 59, 'second': 59, 'microsecond': 999999},
        'day': {'hour': 23, 'minute': 59, 'second': 59, 'microsecond': 999999},
    },
}


def get_date_filters(search_view_arch):
    """Extract date filter configs from search view: {field_name: {custom_options, start/end ranges}}"""
    if not search_view_arch:
        return {}

    date_filters = {}

    try:
        tree = etree.fromstring(search_view_arch)
        for date_filter in tree.xpath(".//filter[@date and @name and not(@invisible='1')]"):
            field_name = date_filter.get("date")

            # Extract range parameters (defaults from web/static/src/search/search_arch_parser.js)
            config = {
                'custom_options': [],
                'start_year': int(date_filter.get('start_year', -2)),
                'end_year': int(date_filter.get('end_year', 0)),
                'start_month': int(date_filter.get('start_month', -2)),
                'end_month': int(date_filter.get('end_month', 0)),
            }

            # Extract custom options from child <filter> elements if present
            # Prefix with "custom_" to match client-side behavior
            child_filters = date_filter.xpath("./filter[@name]")
            if child_filters:
                config['custom_options'] = [f"custom_{child.get('name')}" for child in child_filters]

            date_filters[field_name] = config
    except etree.XMLSyntaxError:
        # If search view is invalid, return empty dict
        return {}

    return date_filters


def validate_date_groupbys(model, date_groupbys):
    if not date_groupbys:
        return

    model_fields = model.fields_get()
    invalid_date_groupbys = []

    for date_groupby in date_groupbys:
        field_name = date_groupby['field_name']
        intervals = date_groupby['intervals']

        invalid_intervals = [i for i in intervals if i not in VALID_INTERVALS]
        if invalid_intervals:
            invalid_date_groupbys.append(f"Invalid intervals '{invalid_intervals}' for field '{field_name}'. Valid intervals: {VALID_INTERVALS}")
            continue

        if not _validate_field_type(model, model_fields, field_name, ['date', 'datetime'], invalid_date_groupbys):
            continue

    if invalid_date_groupbys:
        raise ValueError(f"Invalid date_groupbys: {'; '.join(invalid_date_groupbys)}")


def validate_date_filters(model, filters, action=None):
    """
    Validate date filter objects in a mixed list of filters.
    Accepts a list containing both regular filter names (strings) and date filter objects (dicts).
    Only validates date filter objects, ignoring string filters.
    """
    if not filters:
        return

    # Get search view architecture from action if provided
    search_view_arch = None
    if action:
        search_view = get_search_view(model, action)
        search_view_arch = search_view.get('arch') if search_view else None

    model_fields = model.fields_get()
    invalid_date_filters = []
    date_filter_configs = get_date_filters(search_view_arch) if search_view_arch else {}

    for filter_item in filters:
        # Skip non-date filters (strings)
        if not isinstance(filter_item, dict):
            continue

        date_filter = filter_item
        field_name = date_filter['field_name']
        selected_periods = date_filter['selected_periods']

        if not _validate_field_type(model, model_fields, field_name, ['date', 'datetime'], invalid_date_filters):
            continue

        # Check if field is available as a date filter in the search view
        if field_name not in date_filter_configs:
            available_filters = list(date_filter_configs.keys()) if date_filter_configs else []
            if available_filters:
                invalid_date_filters.append(
                    f"{field_name} is not available as a date filter in the search view. "
                    f"Available date filters: {', '.join(available_filters)}. "
                    f"For {field_name}, use custom_domain with the 'ai_tool_compute_date' tool to get date/time values."
                )
            else:
                invalid_date_filters.append(
                    f"{field_name} is not available as a date filter in the search view (no date filters available). "
                    f"Use custom_domain with the 'ai_tool_compute_date' tool to get date/time values for {field_name}."
                )
            continue  # Skip to next date_filter

        # Validate each period for this field
        config = date_filter_configs[field_name]
        custom_options = config.get('custom_options', [])
        invalid_periods = []

        for period in selected_periods:
            if period in custom_options:
                continue

            if period in VALID_QUARTERS:
                continue

            # check if a valid period with offset (month+-N, year+-N)
            def check_valid_period(period_type):
                match = re.match(rf'^{period_type}([+-]\d{{1,2}})?$', period)
                if match:
                    offset = int(match.group(1) or 0)
                    start_period = config.get(f'start_{period_type}', -2)
                    end_period = config.get(f'end_{period_type}', 0)
                    if not start_period <= offset <= end_period:
                        invalid_periods.append(f"'{period}' (offset {offset} outside range [{start_period}, {end_period}])")
                    return True
                return False

            if not (check_valid_period('month') or check_valid_period('year')):
                invalid_periods.append(
                    f"'{period}' (not a valid pattern. "
                    f"Valid: month, year (with offsets), quarters (first_quarter, second_quarter, third_quarter, fourth_quarter). "
                    f"Custom options: {custom_options if custom_options else 'none'})",
                )

        if invalid_periods:
            invalid_date_filters.append(f"Invalid period formats for field '{field_name}': {', '.join(invalid_periods)}")

    if invalid_date_filters:
        raise ValueError(f"Invalid date_filters: {'; '.join(invalid_date_filters)}")


def compute_date(field_type, user_tz, today, operations=None, pin=None):
    """
    Compute a date/datetime value based on operations and pinning.

    This function allows computing exact date/datetime values for any relative date expression.
    The user thinks in their timezone, and this function handles conversion to UTC transparently.

    Args:
        field_type (str): 'date' or 'datetime' (already validated by caller)
        user_tz (str): Timezone string like 'America/New_York' or 'UTC'
        today (date): Today's date (from fields.Date.context_today, respects test mocking)
        operations (list): Sequential operations to apply (navigate, find_previous, find_next)
        pin (dict): Final anchoring within result (month, day, weekday, weekday_occurrence, time)

    Returns:
        str: Date string in 'YYYY-MM-DD' format for date fields, or
             'YYYY-MM-DD HH:MM:SS' format for datetime fields (in UTC)
    """
    # Start at midnight in user timezone (operations/boundaries/pins will adjust time as needed)
    working_dt = datetime.combine(today, datetime.min.time(), tzinfo=(ZoneInfo(user_tz)))

    for op in operations or []:
        match op["type"]:
            case "navigate":
                working_dt = _compute_date_navigate(working_dt, op)
            case "find_previous":
                working_dt = _compute_date_find_weekday(working_dt, op["weekday"], direction=-1)
            case "find_next":
                working_dt = _compute_date_find_weekday(working_dt, op["weekday"], direction=1)
            case _:
                raise ValueError(f"Unknown operation type: {op['type']}")

    if pin:
        working_dt = _compute_date_apply_pin(working_dt, pin)

    if field_type == "date":
        return working_dt.strftime(DEFAULT_SERVER_DATE_FORMAT)

    working_dt_utc = working_dt.astimezone(UTC)
    return working_dt_utc.strftime(DEFAULT_SERVER_DATETIME_FORMAT)


def _clamp_day_to_month(year, month, day):
    """Clamp a day value to the valid range for the given year and month."""
    max_day = calendar.monthrange(year, month)[1]
    return min(day, max_day)


def _add_months_with_clamping(working_dt, months_offset):
    """
    Add months to a datetime with day clamping.

    Handles month/year overflow and ensures the day is valid for the target month
    (e.g., Jan 31 + 1 month = Feb 28/29, not Feb 31).
    """
    total_months = (working_dt.month - 1) + months_offset  # Convert to 0-indexed
    new_year = working_dt.year + (total_months // 12)
    new_month = (total_months % 12) + 1  # Back to 1-indexed
    new_day = _clamp_day_to_month(new_year, new_month, working_dt.day)
    return working_dt.replace(year=new_year, month=new_month, day=new_day)


def _compute_date_navigate(working_dt, op):
    """Execute a navigate operation on the working datetime."""
    period = op["period"]
    offset = op.get("offset") or 0
    boundary = op.get("boundary")

    if offset < MIN_OFFSET or offset > MAX_OFFSET:
        raise ValueError(f"offset must be between {MIN_OFFSET} and {MAX_OFFSET}")

    match period:
        case "minute":
            result = working_dt + timedelta(minutes=offset)
        case "hour":
            result = working_dt + timedelta(hours=offset)
        case "day":
            result = working_dt + timedelta(days=offset)
        case "week":
            result = working_dt + timedelta(weeks=offset)
        case "month":
            result = _add_months_with_clamping(working_dt, offset)
        case "quarter":
            result = _add_months_with_clamping(working_dt, offset * 3)
        case "year":
            result = _add_months_with_clamping(working_dt, offset * 12)

    # Apply boundary semantics
    if boundary in BOUNDARY_TIME_RESETS:
        time_resets = BOUNDARY_TIME_RESETS[boundary]

        match period:
            case "minute" | "hour" | "day":
                result = result.replace(**time_resets[period])
            case "week":
                # Start of week (Monday): negative offset, End of week (Sunday): positive offset
                days_offset = -result.weekday() if boundary == "start" else 6 - result.weekday()
                result = result + timedelta(days=days_offset)
                result = result.replace(**time_resets['day'])
            case "month":
                day = 1 if boundary == "start" else calendar.monthrange(result.year, result.month)[1]
                result = result.replace(day=day, **time_resets['day'])
            case "quarter":
                quarter = (result.month - 1) // 3 + 1
                month = QUARTER_MONTHS[quarter][0 if boundary == "start" else -1]
                day = 1 if boundary == "start" else calendar.monthrange(result.year, month)[1]
                result = result.replace(month=month, day=day, **time_resets['day'])
            case "year":
                month = 1 if boundary == "start" else 12
                day = 1 if boundary == "start" else 31
                result = result.replace(month=month, day=day, **time_resets['day'])

    return result


def _compute_date_find_weekday(working_dt, target_weekday, direction):
    """
    Helper function to find a specific weekday occurrence.

    Args:
        working_dt: Current datetime to search from
        target_weekday: Target weekday (0=Monday, 6=Sunday)
        direction: 1 for next, -1 for previous

    Returns:
        Datetime of the target weekday occurrence
    """
    if target_weekday < 0 or target_weekday > 6:
        raise ValueError("weekday must be between 0 (Monday) and 6 (Sunday)")

    current_weekday = working_dt.weekday()
    days_offset = (direction * (target_weekday - current_weekday)) % 7 or 7
    result = working_dt + timedelta(days=days_offset * direction)
    return result


def _compute_date_apply_pin(working_dt, pin):
    """Apply pin logic to anchor the working datetime to a specific position.

    Pin structure:
    - pin.day as int: day of month (1-31)
    - pin.day as object: {weekday: int, occurrence?: int}
    - pin.time: string in HH:MM or HH:MM:SS format
    """
    result = working_dt
    if "day" in pin and pin["day"] is not None:
        result = _pin_day(result, pin["day"])
    if "time" in pin and pin["time"] is not None:
        result = _pin_time(result, pin["time"])
    return result


def _pin_day(result, day_value):
    """Anchor the day: a day of the month, or a weekday with an optional occurrence."""
    if isinstance(day_value, int):
        return _pin_day_of_month(result, day_value)
    if isinstance(day_value, dict):
        return _pin_weekday(result, day_value)
    raise ValueError("pin.day must be an integer (1-31) or object {weekday, occurrence?}")


def _pin_day_of_month(result, day):
    if not (1 <= day <= 31):
        raise ValueError("pin.day must be between 1 and 31")
    max_day = calendar.monthrange(result.year, result.month)[1]
    if not (1 <= day <= max_day):
        raise ValueError(
            f"pin.day must be between 1 and {max_day} for {result.year}-{result.month:02d}",
        )
    return result.replace(day=day)


def _pin_weekday(result, day_value):
    """Weekday selector: {weekday: int, occurrence?: int}."""
    if "weekday" not in day_value:
        raise ValueError(
            f"pin.day object must have 'weekday' field. Got: {day_value}"
        )
    target_weekday = day_value["weekday"]
    if not isinstance(target_weekday, int):
        raise TypeError("pin.day.weekday must be an integer (0=Monday, 6=Sunday)")
    if not (0 <= target_weekday <= 6):
        raise ValueError("pin.day.weekday must be between 0 (Monday) and 6 (Sunday)")
    if "occurrence" in day_value and day_value["occurrence"] is not None:
        return _pin_weekday_occurrence(result, target_weekday, day_value["occurrence"])
    # Just find the weekday without occurrence
    return result + timedelta(days=target_weekday - result.weekday())


def _pin_weekday_occurrence(result, target_weekday, occurrence):
    if not isinstance(occurrence, int):
        raise ValueError("pin.day.occurrence must be an integer")
    if not (1 <= occurrence <= 5):
        raise ValueError("pin.day.occurrence must be between 1 and 5")
    first_of_month = result.replace(day=1)
    days_to_first = (target_weekday - first_of_month.weekday()) % 7
    first_occurrence = first_of_month + timedelta(days=days_to_first)
    target_day = first_occurrence + timedelta(weeks=occurrence - 1)
    if target_day.month != result.month:
        raise ValueError(
            f"The {occurrence}th occurrence of weekday {target_weekday} does not exist in month {result.month}",
        )
    return result.replace(day=target_day.day)


def _pin_time(result, time_str):
    """Anchor the time to 'HH:MM' or 'HH:MM:SS'."""
    if not isinstance(time_str, str):
        raise ValueError("pin.time must be a string in 'HH:MM' or 'HH:MM:SS' format")
    time_parts = time_str.split(":")
    if len(time_parts) not in [2, 3]:
        raise ValueError("pin.time must be in 'HH:MM' or 'HH:MM:SS' format")
    try:
        hour = int(time_parts[0])
        minute = int(time_parts[1])
        second = int(time_parts[2]) if len(time_parts) == 3 else 0
    except ValueError:
        raise ValueError("pin.time components must be integers") from None
    if not (0 <= hour <= 23):
        raise ValueError("pin.time hour must be between 0 and 23")
    if not (0 <= minute <= 59):
        raise ValueError("pin.time minute must be between 0 and 59")
    if not (0 <= second <= 59):
        raise ValueError("pin.time second must be between 0 and 59")
    return result.replace(hour=hour, minute=minute, second=second, microsecond=0)


def _validate_field_type(model, model_fields, field_name, allowed_types, error_list):
    field_info = model_fields.get(field_name, {})
    if not field_info:
        error_list.append(f"Field '{field_name}' does not exist in model {model._name}")
        return False

    if field_info.get('type') not in allowed_types:
        type_str = '/'.join(allowed_types)
        actual_type = field_info.get('type')
        error_list.append(f"Field '{field_name}' is not a {type_str} field (type: {actual_type})")
        return False

    return True
