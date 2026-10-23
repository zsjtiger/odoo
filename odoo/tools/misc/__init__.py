# Part of Odoo. See LICENSE file for full copyright and licensing details.
# ruff: noqa: F401
"""Miscellaneous tools used by Odoo, split by concern. The names are re-exported here."""

from .xmlparser import SKIPPED_ELEMENT_TYPES, default_parser
from .formatting import DATETIME_FORMATS_MAP, DATE_LENGTH, DEFAULT_SERVER_DATETIME_FORMAT, DEFAULT_SERVER_DATE_FORMAT, DEFAULT_SERVER_TIME_FORMAT, NON_BREAKING_SPACE, POSIX_TO_LDML, ROUNDING_UNIT_CHARS, _format_time_ago, babel_locale_parse, formatLang, format_amount, format_date, format_datetime, format_decimalized_amount, format_decimalized_number, format_duration, format_time, get_lang, human_size, parse_date, posix_to_ldml
from .security import consteq, hash_sign, hmac, limited_field_access_token, verify_hash_signed, verify_limited_field_access_token
from .containers import Callbacks, Collector, ConstantMapping, DotDict, LastOrderedSet, LazyDict, OrderedSet, ReadonlyDict, Reverse, ReversedIterable, SENTINEL, Sentinel, StackMap, _HashDict, clean_context, freehash, frozendict, groupby, has_list_types, is_list_of, partition, reverse_enumerate, split_every, submap, unique
from .graph import find_circular_dependency, merge_sequences, topological_sort
from .files import file_open, file_open_temporary_directory, file_path, find_in_path
from .system import dumpstacks, exception_to_unicode, exec_pg_environ, find_pg_tool, real_time, replace_exceptions, stripped_sys_argv
from .logs import MungedTracebackLogRecord, lower_logging, mute_logger
from .text import _PrintfArgs, diff_zip, get_diff, html_escape, named_to_positional_printf, remove_accents, str2bool, unquote

__all__ = [
    'DEFAULT_SERVER_DATETIME_FORMAT',
    'DEFAULT_SERVER_DATE_FORMAT',
    'DEFAULT_SERVER_TIME_FORMAT',
    'NON_BREAKING_SPACE',
    'ROUNDING_UNIT_CHARS',
    'SKIPPED_ELEMENT_TYPES',
    'DotDict',
    'LastOrderedSet',
    'OrderedSet',
    'Reverse',
    'babel_locale_parse',
    'clean_context',
    'consteq',
    'exception_to_unicode',
    'file_open',
    'file_open_temporary_directory',
    'file_path',
    'find_circular_dependency',
    'find_in_path',
    'formatLang',
    'format_amount',
    'format_date',
    'format_datetime',
    'format_duration',
    'format_time',
    'frozendict',
    'get_lang',
    'groupby',
    'hash_sign',
    'hmac',
    'html_escape',
    'human_size',
    'is_list_of',
    'merge_sequences',
    'mute_logger',
    'parse_date',
    'partition',
    'posix_to_ldml',
    'real_time',
    'remove_accents',
    'replace_exceptions',
    'reverse_enumerate',
    'split_every',
    'str2bool',
    'topological_sort',
    'unique',
    'verify_hash_signed',
]
