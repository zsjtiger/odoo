# Part of Odoo. See LICENSE file for full copyright and licensing details.
# ruff: noqa: F401
"""The fields of the models. The base class and its helpers are in ``base``; the methods of the field are split by concern in the other modules, and the field types in their own modules. The names are re-exported here."""

from .base import COMPANY_DEPENDENT_FIELDS, Field, IR_MODELS, PYTHON_INEQUALITY_OPERATOR, _logger, determine, resolve_mro

