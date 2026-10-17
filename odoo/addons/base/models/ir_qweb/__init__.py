# Part of Odoo. See LICENSE file for full copyright and licensing details.
# ruff: noqa: F401
"""The QWeb engine: the helpers, the errors, the call stack, the contents, the model that compiles and renders the templates, and the render function. The names are re-exported here."""

# the helpers first, then the modules that use them
from .helpers import ALLOWED_KEYWORD, ETREE_TEMPLATE_REF, FIRST_RSTRIP_REGEXP, LSTRIP_REGEXP, MALICIOUS_SCHEMES, RSTRIP_REGEXP, SPECIAL_DIRECTIVES, TO_VARNAME_REGEXP, T_CALL_SLOT, VARNAME_REGEXP, VOID_ELEMENTS, WHITESPACE_REGEX, _SAFE_QWEB_OPCODES, _id_or_xmlid, _logger, indent_code, keep_query, unsafe_eval
from .errors import QWebError, QWebErrorInfo
from .stack import QwebCallParameters, QwebStackFrame
from .content import QwebContent, QwebJSON, qwebJSON
from .model import IrQweb
from .render import render
