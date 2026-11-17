"""The rendering function of the QWeb engine."""

from __future__ import annotations

from markupsafe import Markup
from collections import defaultdict
from collections.abc import Callable
from lxml import etree
from odoo.modules.registry import _REGISTRY_CACHES
from odoo.tools.lru import LRU

from .model import IrQweb

def render(template_name: str | int, values: dict, load: Callable[[str], tuple[etree._Element, str]], **options) -> Markup:
    """ Rendering of a qweb template without database and outside the registry.
    (Widget, field, or asset rendering is not implemented.)
    :param template_name: template identifier
    :param values: template values to be used for rendering
    :param load: function like `load(template_name)` which returns a tuple
        (etree, xmlid) from the given template name (from initial rendering or
        template `t-call`).
    :param options: used to compile the template
    :returns: bytes marked as markup-safe
    """
    class MockRegistry:
        def __init__(self):
            self.db_name = None
            self._template_code__ = LRU(_REGISTRY_CACHES['templates'])

    registry = MockRegistry()

    class MockIrQWeb(IrQweb):
        _register = False               # not visible in real registry

        pool = registry

        def _get_template_info(self, id_or_xmlid):
            return defaultdict(lambda: None, id=id_or_xmlid)

        def _preload_trees(self, refs):
            values = {}
            for ref in refs:
                tree, vid = self.env.context['load'](ref)
                values[ref] = values[vid] = {
                    'tree': tree,
                    'template': etree.tostring(tree, encoding='unicode'),
                    'xmlid': vid,
                    'ref': None,
                }
            return values

        def _load(self, ref):
            """
            Load the template referenced by ``ref``.

            :returns: The loaded template (as string or etree) and its
                identifier
            :rtype: Tuple[Union[etree, str], Optional[str, int]]
            """
            return self.env.context['load'](ref)

        def _prepare_environment(self, values):
            values['true'] = True
            values['false'] = False
            return self

        def _get_field(self, *args):
            raise NotImplementedError("Fields are not allowed in this rendering mode. Please use \"env['ir.qweb']._render\" method")

        def _get_widget(self, *args):
            raise NotImplementedError("Widgets are not allowed in this rendering mode. Please use \"env['ir.qweb']._render\" method")

        def _get_asset_nodes(self, *args):
            raise NotImplementedError("Assets are not allowed in this rendering mode. Please use \"env['ir.qweb']._render\" method")

    class MockCr:
        def __init__(self):
            self.cache = {}

    class MockTransaction:
        def __init__(self):
            self.ormcaches__ = {
                cache_name: LRU(cache_size)
                for cache_name, cache_size in _REGISTRY_CACHES.items()
            }
            self.registry = registry

    class MockEnv(dict):
        def __init__(self):
            super().__init__()
            self.context = {}
            self.cr = MockCr()
            self.transaction = MockTransaction()
            self.registry = registry

        def __call__(self, cr=None, user=None, context=None, su=None):
            """ Return an mocked environment based and update the sent context.
                Allow to use `ir_qweb.with_context` with sand boxed qweb.
            """
            env = MockEnv()
            env.context.update(self.context if context is None else context)
            return env

    renderer = MockIrQWeb(MockEnv(), tuple(), tuple())
    return renderer._render(template_name, values, load=load, minimal_qcontext=True, **options)
