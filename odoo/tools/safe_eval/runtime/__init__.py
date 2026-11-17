# Part of Odoo. See LICENSE file for full copyright and licensing details.
# ruff: noqa: F401
"""Safe evaluation of the Python expressions and code of Odoo. The names are re-exported here."""

from .errors import UnsafeContextError, UnsafeError, UnsafeModuleError, UnsafeObjectError, UnsafePolicy, _logger_runtime, handle_unsafe_error, unsafe_policy
from .transformer import _SafeTransformer, encoder_ctx, safe_transform, safe_transformer
from .whitelist import EVENTS, TOOL_ID, UnsafeClassError, UnsafeFunctionError, UnsafeInstanceError, _MONITORING_BUILTINS, _SafeChecker, _SafeGenerator, _SafeWhitelist, _initialize_safe_whitelist, add_monitoring, assert_safe_context, monitoring_call, safe_call, safe_call_deco, safe_checker, safe_gen_wrapper, safe_whitelist

__all__ = [
    'safe_checker',
    'safe_transform',
    'safe_whitelist',
    'unsafe_policy',
]
