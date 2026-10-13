# Part of Odoo. See LICENSE file for full copyright and licensing details.
# ruff: noqa: F401

from odoo.tools import constants
from odoo.tools import urls
from odoo.tools.parse_version import parse_version
from odoo.tools.files.binary import BinaryBytes, BinaryValue
from odoo.tools.config import config
from odoo.tools.numeric.float_utils import float_compare, float_div, float_is_zero, float_repr, float_round, float_split, float_split_str
from odoo.tools.func import classproperty, conditional, lazy, lazy_classproperty, reset_cached_properties
from odoo.tools.text.i18n import format_list, py_to_js_locale
from odoo.tools.json import json_default
from odoo.tools.mail import email_domain_extract, email_domain_normalize, email_normalize, email_normalize_all, email_split, encapsulate_email, formataddr, html2plaintext, html_normalize, html_sanitize, is_html_empty, parse_contact_from_email, plaintext2html, single_email_re
from odoo.tools.misc import DEFAULT_SERVER_DATETIME_FORMAT, DEFAULT_SERVER_DATE_FORMAT, DEFAULT_SERVER_TIME_FORMAT, DotDict, LastOrderedSet, NON_BREAKING_SPACE, OrderedSet, ROUNDING_UNIT_CHARS, Reverse, SKIPPED_ELEMENT_TYPES, babel_locale_parse, clean_context, consteq, exception_to_unicode, file_open, file_open_temporary_directory, file_path, find_circular_dependency, find_in_path, formatLang, format_amount, format_date, format_datetime, format_duration, format_time, frozendict, get_lang, groupby, hash_sign, hmac, html_escape, human_size, is_list_of, merge_sequences, mute_logger, parse_date, partition, posix_to_ldml, real_time, remove_accents, replace_exceptions, reverse_enumerate, split_every, str2bool, topological_sort, unique, verify_hash_signed
from odoo.tools.sql import SQL, drop_view_if_exists
from odoo.tools.text.translate import _, html_translate, xml_translate, LazyTranslate
from odoo.tools.xml.xml_utils import cleanup_xml_node, load_xsd_files_from_url, validate_xml_from_attachment
from odoo.tools.loading.convert import convert_file
from odoo.tools.sql.set_expression import SetDefinitions


def __getattr__(name):
    import warnings  # noqa: PLC0415
    if name in ('cache', 'ormcache'):
        warnings.warn("Since 20.0 import ormcache from odoo.api", DeprecationWarning, stacklevel=2)
        from odoo.orm.models import cache  # noqa: PLC0415
        return cache if name == 'cache' else cache.ormcache
    raise AttributeError(name=name)
