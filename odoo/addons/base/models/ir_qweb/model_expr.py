"""The compilation of the expressions of the templates: the tokens, the booleans and the strings."""

from __future__ import annotations

import ast
import io
import token
import tokenize
from collections.abc import Buffer
from odoo.tools import safe_eval
from odoo.tools.safe_eval import (
    assert_valid_codeobj,
    safe_transform,
)
from .helpers import ALLOWED_KEYWORD, _SAFE_QWEB_OPCODES


def _compile_expr_tokens(self, tokens, allowed_keys, argument_names=None, raise_on_missing=False):
    """ Transform the list of token coming into a python instruction in
            textual form by adding the namepaces for the dynamic values.

            Example: `5 + a + b.c` to be `5 + values.get('a') + values['b'].c`
            Unknown values are considered to be None, but using `values['b']`
            gives a clear error message in cases where there is an attribute for
            example (have a `KeyError: 'b'`, instead of `AttributeError: 'NoneType'
            object has no attribute 'c'`).

            @returns str
        """
    # Finds and extracts the current "scope"'s "allowed values": values
    # which should not be accessed through the environment's namespace:
    # * the local variables of a lambda should be accessed directly e.g.
    #     lambda a: a + b should be compiled to lambda a: a + values['b'],
    #     since a is local to the lambda it has to be accessed directly
    #     but b needs to be accessed through the rendering environment
    # * similarly for a comprehensions [a + b for a in c] should be
    #     compiledto [a + values.get('b') for a in values.get('c')]
    # to avoid the risk of confusion between nested lambdas / comprehensions,
    # this is currently performed independently at each level of brackets
    # nesting (hence the function being recursive).
    open_bracket_index = -1
    bracket_depth = 0

    argument_name = '_arg_%s__'
    argument_names = argument_names or []

    for index, t in enumerate(tokens):
        if t.exact_type in [token.LPAR, token.LSQB, token.LBRACE]:
            bracket_depth += 1
        elif t.exact_type in [token.RPAR, token.RSQB, token.RBRACE]:
            bracket_depth -= 1
        elif bracket_depth == 0 and t.exact_type == token.NAME:
            string = t.string
            if string == 'lambda': # lambda => allowed values for the current bracket depth
                for i in range(index + 1, len(tokens)):
                    t = tokens[i]
                    if t.exact_type == token.NAME:
                        argument_names.append(t.string)
                    elif t.exact_type == token.COMMA:
                        pass
                    elif t.exact_type == token.COLON:
                        break
                    elif t.exact_type == token.EQUAL:
                        raise NotImplementedError('Lambda default values are not supported')
                    else:
                        raise NotImplementedError('This lambda code style is not implemented.')
            elif string == 'for': # list comprehensions => allowed values for the current bracket depth
                for i in range(index + 1, len(tokens)):
                    t = tokens[i]
                    if t.exact_type == token.NAME:
                        if t.string == 'in':
                            break
                        argument_names.append(t.string)
                    elif t.exact_type in [token.COMMA, token.LPAR, token.RPAR]:
                        pass
                    else:
                        raise NotImplementedError('This loop code style is not implemented.')

    # Use bracket to nest structures.
    # Recursively processes the "sub-scopes", and replace their content with
    # a compiled node. During this recursive call we add to the allowed
    # values the values provided by the list comprehension, lambda, etc.,
    # previously extracted.
    index = 0
    open_bracket_index = -1
    bracket_depth = 0

    while index < len(tokens):
        t = tokens[index]
        string = t.string

        if t.exact_type in [token.LPAR, token.LSQB, token.LBRACE]:
            if bracket_depth == 0:
                open_bracket_index = index
            bracket_depth += 1
        elif t.exact_type in [token.RPAR, token.RSQB, token.RBRACE]:
            bracket_depth -= 1
            if bracket_depth == 0:
                code = self._compile_expr_tokens(
                    tokens[open_bracket_index + 1:index],
                    list(allowed_keys),
                    list(argument_names),
                    raise_on_missing,
                )
                code = tokens[open_bracket_index].string + code + t.string
                tokens[open_bracket_index:index + 1] = [tokenize.TokenInfo(token.QWEB, code, tokens[open_bracket_index].start, t.end, '')]
                index = open_bracket_index

        index += 1

    # The keys will be namespaced by values if they are not allowed. In
    # order to have a clear keyError message, this will be replaced by
    # values['key'] for certain cases (for example if an attribute is called
    # key.attrib, or an index key[0] ...)
    code = []
    index = 0
    pos = tokens and tokens[0].start # to keep level when use expr on multi line
    while index < len(tokens):
        t = tokens[index]
        string = t.string

        if t.start[0] != pos[0]:
            pos = (t.start[0], 0)
        space = t.start[1] - pos[1]
        if space:
            code.append(' ' * space)
        pos = t.start

        if t.exact_type == token.NAME:
            if '__' in string:
                raise SyntaxError(f"Using variable names with '__' is not allowed: {string!r}")
            if string == 'lambda': # lambda => allowed values
                code.append('lambda ')
                index += 1
                while index < len(tokens):
                    t = tokens[index]
                    if t.exact_type == token.NAME and t.string in argument_names:
                        code.append(argument_name % t.string)
                    if t.exact_type in [token.COMMA, token.COLON]:
                        code.append(t.string)
                    if t.exact_type == token.COLON:
                        break
                    index += 1
                if t.end[0] != pos[0]:
                    pos = (t.end[0], 0)
                else:
                    pos = t.end
            elif string in argument_names:
                code.append(argument_name % t.string)
            elif string in allowed_keys:
                code.append(string)
            elif index + 1 < len(tokens) and tokens[index + 1].exact_type == token.EQUAL: # function kw
                code.append(string)
            elif index > 0 and tokens[index - 1] and tokens[index - 1].exact_type == token.DOT:
                code.append(string)
            elif raise_on_missing or index + 1 < len(tokens) and tokens[index + 1].exact_type in [token.DOT, token.LPAR, token.LSQB, token.QWEB]:
                # Should have values['product'].price to raise an error when get
                # the 'product' value and not an 'NoneType' object has no
                # attribute 'price' error.
                code.append(f'values[{string!r}]')
            else:
                # not assignation allowed, only getter
                code.append(f'values.get({string!r})')
        elif t.type not in [tokenize.ENCODING, token.ENDMARKER, token.DEDENT]:
            code.append(string)

        if t.end[0] != pos[0]:
            pos = (t.end[0], 0)
        else:
            pos = t.end

        index += 1

    return ''.join(code)


def _compile_expr(self, expr, compile_context, raise_on_missing=False):
    """Transform string coming into a python instruction in textual form by
        adding the namepaces for the dynamic values.
        This method tokenize the string and call ``_compile_expr_tokens``
        method.

        :param expr: string: python expression
        :param bool raise_on_missing:
            Compile has `values['product'].price` instead of
            `values.get('product').price` to raise an error when get the
            'product' value and not an 'NoneType' object has no attribute
            'price' error.
        """
    # Parentheses are useful for compiling multi-line expressions such as
    # conditions existing in some templates. (see test_compile_expr tests)
    readable = io.BytesIO(f"({expr or ''})".encode('utf-8'))
    try:
        tokens = list(tokenize.tokenize(readable.readline))
    except tokenize.TokenError:
        raise ValueError(f"Can not compile expression: {expr}")

    expression = self._compile_expr_tokens(tokens, ALLOWED_KEYWORD, raise_on_missing=raise_on_missing)

    if safe_eval.unsafe_policy():
        # Note: if the generated safe expression is evaluated using `safe_eval`,
        # there will be double wrapping: `CALL_ID(CALL_ID(...))`.
        # Example: `_guess_qweb_variables.qweb_like_eval`
        tree = ast.parse(expression.strip(), mode='eval')
        tree = safe_transform(tree)
        expression = ast.unparse(tree)

    assert_valid_codeobj(_SAFE_QWEB_OPCODES, compile(expression, '<>', 'eval'), expr)

    return f"({expression})"


def _compile_bool(self, attr, default=False):
    """Convert the statements as a boolean."""
    if attr:
        if attr is True:
            return True
        attr = attr.lower()
        if attr in ('false', '0'):
            return False
        elif attr in ('true', '1'):
            return True
    return bool(default)


def _compile_to_str(self, expr):
    """ Generates a text value (an instance of text_type) from an arbitrary
            source.
        """
    if expr is None or expr is False:
        return ''

    if isinstance(expr, str):
        return expr
    elif isinstance(expr, Buffer):
        return bytes(expr).decode()
    else:
        return str(expr)
