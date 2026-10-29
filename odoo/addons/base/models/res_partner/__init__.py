# Part of Odoo. See LICENSE file for full copyright and licensing details.
# ruff: noqa: F401
"""The partners: the helpers, the categories, the partners and their industries. The names are re-exported here."""

# the helpers first, then the models in the order of their definitions: the order of the classes is the order of their extensions
from .helpers import EU_EXTRA_VAT_CODES, EU_EXTRA_VAT_CODES_INV, _lang_get, _lt, _ref_vat, _tz_get, _tzs
from .category import ResPartnerCategory
from .partner import ResPartner
from .industry import ResPartnerIndustry
