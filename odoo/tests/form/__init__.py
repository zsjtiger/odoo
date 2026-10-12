# Part of Odoo. See LICENSE file for full copyright and licensing details.
# ruff: noqa: F401
"""Form test helper of Odoo: the form simulating the user in the tests, split by concern. The names are re-exported here."""

from .utils import Dotter, MODIFIER_ALIASES, _cleanup_from_default, convert_read_to_form, get_static_context
from .values import M2MValue, O2MValue, UpdateDict, X2MValue
from .proxies import M2MProxy, X2MProxy
from .form import Form, O2MForm, O2MProxy

__all__ = [
    'Dotter',
    'Form',
    'M2MProxy',
    'M2MValue',
    'MODIFIER_ALIASES',
    'O2MForm',
    'O2MProxy',
    'O2MValue',
    'UpdateDict',
    'X2MProxy',
    'X2MValue',
    'convert_read_to_form',
    'get_static_context',
]
