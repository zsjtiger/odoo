"""The helpers of the QWeb engine: the constants, the regular expressions and the code helpers."""

from __future__ import annotations

import fnmatch
import logging
import re
import textwrap
import token
import werkzeug
from itertools import count
from odoo.tools.safe_eval import (
    _BLACKLIST,
    _BUILTINS,
    _EXPR_OPCODES,
    to_opcodes,
)
from odoo.http import request
from odoo.addons.base.models.ir_ui_view import MOVABLE_BRANDING

_logger = logging.getLogger('odoo.addons.base.models.ir_qweb')


token.QWEB = token.NT_OFFSET - 1


token.tok_name[token.QWEB] = 'QWEB'


_SAFE_QWEB_OPCODES = _EXPR_OPCODES.union(to_opcodes([
    'MAKE_FUNCTION', 'CALL_FUNCTION', 'CALL_FUNCTION_KW', 'CALL_FUNCTION_EX',
    'CALL_METHOD', 'LOAD_METHOD',

    'GET_ITER', 'FOR_ITER', 'YIELD_VALUE',
    'JUMP_FORWARD', 'JUMP_ABSOLUTE', 'JUMP_BACKWARD',
    'JUMP_IF_FALSE_OR_POP', 'JUMP_IF_TRUE_OR_POP', 'POP_JUMP_IF_FALSE', 'POP_JUMP_IF_TRUE',

    'LOAD_NAME', 'LOAD_ATTR',
    'LOAD_FAST', 'STORE_FAST', 'UNPACK_SEQUENCE',
    'STORE_SUBSCR',
    'LOAD_GLOBAL',
    'EXTENDED_ARG',
    # Following opcodes were added in 3.11 https://docs.python.org/3/whatsnew/3.11.html#new-opcodes
    'RESUME',
    'CALL',
    'PRECALL',
    'PUSH_NULL',
    'KW_NAMES',
    'FORMAT_VALUE', 'BUILD_STRING',
    'RETURN_GENERATOR',
    'SWAP',
    'POP_JUMP_FORWARD_IF_FALSE', 'POP_JUMP_FORWARD_IF_TRUE',
    'POP_JUMP_BACKWARD_IF_FALSE', 'POP_JUMP_BACKWARD_IF_TRUE',
    'POP_JUMP_FORWARD_IF_NONE', 'POP_JUMP_FORWARD_IF_NOT_NONE',
    'POP_JUMP_BACKWARD_IF_NONE', 'POP_JUMP_BACKWARD_IF_NOT_NONE',
    # 3.12 https://docs.python.org/3/whatsnew/3.12.html#new-opcodes
    'END_FOR',
    'LOAD_FAST_AND_CLEAR',
    'POP_JUMP_IF_NOT_NONE', 'POP_JUMP_IF_NONE',
    'RERAISE',
    'CALL_INTRINSIC_1',
    'STORE_SLICE',
    # 3.13
    'CALL_KW', 'LOAD_FAST_LOAD_FAST',
    'STORE_FAST_STORE_FAST', 'STORE_FAST_LOAD_FAST',
    'CONVERT_VALUE', 'FORMAT_SIMPLE', 'FORMAT_WITH_SPEC',
    'SET_FUNCTION_ATTRIBUTE',
    # 3.14 c.f. safe_eval
    'LOAD_FAST_BORROW', 'LOAD_FAST_BORROW_LOAD_FAST_BORROW',
    'POP_ITER', 'LOAD_COMMON_CONSTANT', 'NOT_TAKEN',
    'JUMP_BACKWARD_NO_INTERRUPT',
])) - _BLACKLIST


unsafe_eval = eval


VOID_ELEMENTS = frozenset([
    'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'keygen',
    'link', 'menuitem', 'meta', 'param', 'source', 'track', 'wbr'])


ALLOWED_KEYWORD = frozenset(['False', 'None', 'True', 'and', 'as', 'elif', 'else', 'for', 'if', 'in', 'is', 'not', 'or'] + list(_BUILTINS))


RSTRIP_REGEXP = re.compile(r'\n[ \t]*$')


LSTRIP_REGEXP = re.compile(r'^[ \t]*\n')


FIRST_RSTRIP_REGEXP = re.compile(r'^(\n[ \t]*)+(\n[ \t])')


VARNAME_REGEXP = re.compile(r'^[A-Za-z_][A-Za-z0-9_]*$')


TO_VARNAME_REGEXP = re.compile(r'[^A-Za-z0-9_]+')


SPECIAL_DIRECTIVES = {'t-translation', 't-ignore', 't-title', 'id', 'name'} | set(MOVABLE_BRANDING)


T_CALL_SLOT = '0'


ETREE_TEMPLATE_REF = count()


MALICIOUS_SCHEMES = re.compile(r'javascript:(?!((window\.)?)history\.back\(\)$)', re.I).findall


WHITESPACE_REGEX = re.compile(r'[\s\x00-\x08\x0B\x0C\x0E-\x19]+')


def _id_or_xmlid(ref):
    try:
        return int(ref)
    except ValueError:
        return ref


def indent_code(code, level):
    """Indent the code to respect the python syntax."""
    return textwrap.indent(textwrap.dedent(code).strip(), ' ' * 4 * level)


def keep_query(*keep_params, **additional_params):
    """
    Generate a query string keeping the current request querystring's parameters specified
    in ``keep_params`` and also adds the parameters specified in ``additional_params``.

    Multiple values query string params will be merged into a single one with comma seperated
    values.

    The ``keep_params`` arguments can use wildcards too, eg:

        keep_query('search', 'shop_*', page=4)
    """
    if not keep_params and not additional_params:
        keep_params = ('*',)
    params = additional_params.copy()
    qs_keys = list(request.httprequest.args) if request else []
    for keep_param in keep_params:
        for param in fnmatch.filter(qs_keys, keep_param):
            if param not in additional_params and param in qs_keys:
                params[param] = request.httprequest.args.getlist(param)
    return werkzeug.urls.url_encode(params)
