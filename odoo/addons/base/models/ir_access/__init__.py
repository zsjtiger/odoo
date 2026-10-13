# Part of Odoo. See LICENSE file for full copyright and licensing details.
# ruff: noqa: F401
"""The access rights of the records: the constants and the model. The names are re-exported here."""

# the helpers first, then the model that uses them
from .helpers import ACCESS_ERROR_MESSAGE, CRUD_SELECTION, IN_SELECTION, OPERATION_NAME, AccessInfo
from .access import IrAccess
