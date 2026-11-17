# Part of Odoo. See LICENSE file for full copyright and licensing details.
# ----------------------------------------------------------
# ir_http: the routing of the ``ir.http`` model. The names are re-exported here.
# ----------------------------------------------------------
# ruff: noqa: F401
from .requirements import AuthRequirements, CheckIdentityResult
from .converters import ModelConverter, ModelsConverter, RequestUID, SignedIntConverter
from .rules import FasterRule, LazyCompiledBuilder
from .base import EXTENSION_TO_WEB_MIMETYPES, IrHttp
