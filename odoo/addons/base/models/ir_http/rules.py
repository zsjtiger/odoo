# Part of Odoo. See LICENSE file for full copyright and licensing details.
# ----------------------------------------------------------
# ir_http routing rules
# ----------------------------------------------------------
import werkzeug.routing


class LazyCompiledBuilder:
    def __init__(self, rule, _compile_builder, append_unknown):
        self.rule = rule
        self._callable = None
        self._compile_builder = _compile_builder
        self._append_unknown = append_unknown

    def __get__(self, *args):
        # Rule.compile will actually call
        #
        #   self._build = self._compile_builder(False).__get__(self, None)
        #   self._build_unknown = self._compile_builder(True).__get__(self, None)
        #
        # meaning the _build and _build unkown will contain _compile_builder().__get__(self, None).
        # This is why this override of __get__ is needed.
        return self

    def __call__(self, *args, **kwargs):
        if self._callable is None:
            self._callable = self._compile_builder(self._append_unknown).__get__(self.rule, None)
            del self.rule
            del self._compile_builder
            del self._append_unknown
        return self._callable(*args, **kwargs)


class FasterRule(werkzeug.routing.Rule):
    """
    _compile_builder is a major part of the routing map generation and rules
    are actually not build so often.
    This classe makes calls to _compile_builder lazy
    """
    def _compile_builder(self, append_unknown=True):
        return LazyCompiledBuilder(self, super()._compile_builder, append_unknown)
