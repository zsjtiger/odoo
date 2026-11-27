# Part of Odoo. See LICENSE file for full copyright and licensing details.
# ruff: noqa: F401
"""The views of the registry: the helpers, the customized views, the name manager, the views, the reset wizard and the extensions of the base model. The names are re-exported here."""

# the helpers first, then the models in the order of their definitions: the order of the classes is the order of their extensions
from .helpers import COMP_REGEX, MOVABLE_BRANDING, QUARTER_PERIODS, RELATIVE_PERIODS, TRANSLATED_ATTRS_RE, VIEW_MODIFIERS, WRONGCLASS, _hasclass, _logger, att_names, get_view_arch_from_file, ref_re, xpath_utils
from .custom import IrUiViewCustom
from .name_manager import NameManager
from .view import IrUiView
from .reset_wizard import ResetViewArchWizard
from .base import Base
