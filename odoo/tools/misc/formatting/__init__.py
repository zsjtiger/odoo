# Part of Odoo. See LICENSE file for full copyright and licensing details.
# ruff: noqa: F401
"""The formatting of the values: the languages, the dates and durations, and the numbers and amounts. The names are re-exported here."""

from .languages import babel_locale_parse, get_lang
from .dates import DATETIME_FORMATS_MAP, DATE_LENGTH, DEFAULT_SERVER_DATETIME_FORMAT, DEFAULT_SERVER_DATE_FORMAT, DEFAULT_SERVER_TIME_FORMAT, POSIX_TO_LDML, _format_time_ago, format_date, format_datetime, format_duration, format_time, parse_date, posix_to_ldml
from .numbers import NON_BREAKING_SPACE, ROUNDING_UNIT_CHARS, format_amount, format_decimalized_amount, format_decimalized_number, formatLang, human_size
