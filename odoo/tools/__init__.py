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
from odoo.tools.mail import *
from odoo.tools.misc import *
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
