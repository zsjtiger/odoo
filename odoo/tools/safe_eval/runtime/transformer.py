"""Transformer of the Python code: it rewrites the calls and the attributes to their safe versions."""

import ast
from contextvars import ContextVar

from . import errors
from .errors import UnsafePolicy, _logger_runtime

is_gen_ctx: ContextVar[bool] = ContextVar('is_gen_ctx', default=False)


class _SafeTransformer(ast.NodeTransformer):
    """
    Code transformer that wraps calls with :func:`_safe_eval_call` in
    order to check that the arguments are "safe".
    """

    # In Qweb, we use the transformer to modify the python expression.
    # The ast will not be compiled, but instead "unparsed" in the transpiled template.
    # The expression will be used later and therefore re-parsed.
    # It is therefore necessary for the identifiers to be valid.

    CALL_ID = '_safe_eval_call'
    DECO_ID = '_safe_eval_deco'
    GEN_FUNC_ID = '_safe_eval_gen_func'
    GEN_ITER_ID = '_safe_eval_gen_iter'

    def visit_Call(self, node):
        """
        Transforms:
            func(*args, **kwargs)

        Into:
            _safe_eval_call(func, *args, **kwargs)
        """
        self.generic_visit(node)
        call = ast.Call(
            func=ast.Name(id=self.CALL_ID, ctx=ast.Load()),
            args=[node.func, *node.args],
            keywords=node.keywords)
        ast.copy_location(call, node)
        ast.copy_location(call.func, node)
        return call

    def visit_FunctionDef(self, node):
        """
        Transforms:
            @decorator_A
            @decorator_B
            def func():
                pass

        Into:
            @_safe_eval_deco(decorator_A)
            @_safe_eval_deco(decorator_B)
            def func():
                pass

        Note:
            If the function produces a generator, a decorator is added to wrap
            the result with `_safe_eval_gen_func`.
        """
        token = is_gen_ctx.set(False)
        try:
            self.generic_visit(node)
            is_gen = is_gen_ctx.get()
        finally:
            is_gen_ctx.reset(token)

        if not node.decorator_list and not is_gen:
            return node

        new_decorators = []

        for decorator in node.decorator_list:
            wrapped_decorator = ast.Call(
                func=ast.Name(id=self.DECO_ID, ctx=ast.Load()),
                args=[decorator],
                keywords=[],
            )
            ast.copy_location(wrapped_decorator, decorator)
            ast.copy_location(wrapped_decorator.func, decorator)
            new_decorators.append(wrapped_decorator)

        if is_gen:
            gen_func_wrapper = ast.Name(id=self.GEN_FUNC_ID, ctx=ast.Load())
            ast.copy_location(gen_func_wrapper, node)
            new_decorators.append(gen_func_wrapper)

        node.decorator_list = new_decorators

        return node

    def visit_Yield(self, node):
        """ Set parent function definition as a generator function """
        is_gen_ctx.set(True)
        return self.generic_visit(node)

    visit_YieldFrom = visit_Yield

    def visit_GeneratorExp(self, node):
        """
        Transforms:
            (_ for _ in [])

        Into:
            _safe_eval_gen_iter((_ for _ in []))
        """
        self.generic_visit(node)
        call = ast.Call(
            func=ast.Name(id=self.GEN_ITER_ID, ctx=ast.Load()),
            args=[node],
            keywords=[],
        )
        ast.copy_location(call, node)
        ast.copy_location(call.func, node)
        return call

    def visit_Try(self, node):
        """ Ensure no bare except is used """
        self.generic_visit(node)

        for handler in node.handlers:
            if not handler.type:
                _logger_runtime.warning(
                    'Use blind except (`except Exception:`) instead of bare except',
                )
                if errors.unsafe_policy() >= UnsafePolicy.RAISE:
                    raise SyntaxError('You cannot use bare except, use `except Exception:`')

        return node

    def visit_AsyncFunctionDef(self, node):
        # Prevent the use of `AsyncFor` node
        _logger_runtime.warning(
            'Asynchronous function should not be used',
        )
        if errors.unsafe_policy() >= UnsafePolicy.RAISE:
            raise SyntaxError('You cannot use asynchronous function')

        return self.visit_FunctionDef(node)

    def visit_comprehension(self, node):
        """ Ensure async is not used """
        self.generic_visit(node)

        if node.is_async:
            _logger_runtime.warning(
                'Asynchronous comprehension should not be used',
            )
            if errors.unsafe_policy() >= UnsafePolicy.RAISE:
                raise SyntaxError('You cannot use asynchronous comprehension')

        return node


encoder_ctx = ContextVar('encoder_ctx')


safe_transformer = _SafeTransformer()


safe_transform = safe_transformer.visit
