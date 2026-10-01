#!/usr/bin/env python3
# Part of Odoo. See LICENSE file for full copyright and licensing details.
"""Check that the core packages of Odoo only import downwards.

The layers are documented in ``odoo/ARCHITECTURE.md``. A module may import
modules of its own layer and of lower layers. Only the imports executed when
the module is loaded are checked: imports inside functions and inside
``if TYPE_CHECKING:`` blocks are allowed to reference upper layers.

Usage: ``setup/check_layers.py [--verbose]``. Exits with status 1 when a
violation is found.
"""
import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent / 'odoo'

# ordered from the bottom to the top, as (layer, module prefixes)
LAYERS = [
    (0, ['odoo.release', 'odoo.exceptions', 'odoo.tools']),
    (1, ['odoo.core']),
    (2, ['odoo.orm', 'odoo.api', 'odoo.fields', 'odoo.models']),
    (3, ['odoo.modules']),
    (4, ['odoo.http', 'odoo.service']),
    (5, ['odoo.cli', 'odoo.tests', 'odoo.__main__', 'odoo.addons']),
]

# namespace packages holding code from elsewhere, not modules of a layer
NAMESPACES = {'odoo.addons', 'odoo.upgrade'}

# known exceptions, as (importing module, imported module)
ALLOWED = {
    # the country groups used by the validators are defined in the base addon
    ('odoo.tools.partner_identifiers', 'odoo.addons.base.models.res_country'),
}


def layer_of(name):
    if name in NAMESPACES:
        return None
    best = None
    for layer, prefixes in LAYERS:
        for prefix in prefixes:
            if (name == prefix or name.startswith(prefix + '.')) and (
                best is None or len(prefix) > len(best[1])
            ):
                best = (layer, prefix)
    return best[0] if best else None


def module_name(path):
    parts = list(path.relative_to(ROOT.parent).with_suffix('').parts)
    if parts[-1] == '__init__':
        parts.pop()
    return '.'.join(parts)


def is_type_checking(test):
    return (isinstance(test, ast.Name) and test.id == 'TYPE_CHECKING') or (
        isinstance(test, ast.Attribute) and test.attr == 'TYPE_CHECKING'
    )


def load_time_imports(tree):
    """Yield the import nodes executed when the module is loaded."""
    def visit(nodes):
        for node in nodes:
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                yield node
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
                continue
            elif isinstance(node, ast.If) and is_type_checking(node.test):
                yield from visit(node.orelse)
            else:
                yield from visit(ast.iter_child_nodes(node))
    yield from visit(tree.body)


def imported_names(node, current, is_package):
    if isinstance(node, ast.Import):
        return [alias.name for alias in node.names]
    if node.level:
        base = current.split('.')
        base = base[:len(base) - node.level + (1 if is_package else 0)]
        prefix = '.'.join(base + ([node.module] if node.module else []))
    else:
        prefix = node.module
    # 'from odoo import api' imports the module 'odoo.api'
    return [f'{prefix}.{alias.name}' for alias in node.names] if prefix == 'odoo' else [prefix]


def main():
    verbose = '--verbose' in sys.argv
    violations = []
    for path in sorted(ROOT.rglob('*.py')):
        rel = path.relative_to(ROOT).parts
        if rel[0] == 'addons' or 'upgrade_code' in rel:
            continue
        current = module_name(path)
        src_layer = layer_of(current)
        if src_layer is None:
            continue
        tree = ast.parse(path.read_bytes(), str(path))
        for node in load_time_imports(tree):
            for name in imported_names(node, current, path.name == '__init__.py'):
                dst_layer = layer_of(name)
                if dst_layer is not None and dst_layer > src_layer and (current, name) not in ALLOWED:
                    violations.append(f'{path.relative_to(ROOT.parent)}:{node.lineno}: '
                                      f'{current} (L{src_layer}) imports {name} (L{dst_layer})')
    for violation in violations:
        print(violation)  # noqa: T201
    if verbose or violations:
        print(f'{len(violations)} layering violation(s)')  # noqa: T201
    return 1 if violations else 0


if __name__ == '__main__':
    sys.exit(main())
