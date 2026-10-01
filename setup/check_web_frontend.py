#!/usr/bin/env python3
# Part of Odoo. See LICENSE file for full copyright and licensing details.
"""Check the JavaScript code of the web client.

1. every module imported by the JS code of the repository exists;
2. the folders of web/static/src only import downwards, see
   addons/web/ARCHITECTURE.md;
3. every path of the asset bundles of the manifests matches a file.

Usage: ``setup/check_web_frontend.py [--verbose]``. Exits with status 1
when a problem is found.
"""
import ast
import glob
import re
import sys
from pathlib import Path, PurePosixPath

REPO = Path(__file__).resolve().parent.parent
ADDONS_DIRS = [REPO / 'addons', REPO / 'odoo' / 'addons']
WEB_SRC = REPO / 'addons' / 'web' / 'static' / 'src'

# folders of web/static/src, from the bottom to the top
LAYERS = [
    (0, ['libs', 'owl2', 'core']),
    (1, ['search', 'public']),
    (2, ['model']),
    (3, ['views']),
    (4, ['webclient']),
    (5, ['boot', 'main', 'start', 'env', 'session', 'module_loader', 'service_worker', 'polyfills']),
]
# leaf modules of the startup that every layer may use
SHARED = {'boot/session', 'boot/env', 'session', 'env'}
# asset paths that are not files of the repository
VIRTUAL_ASSETS = {
    'web/static/asset_styles_company_report.scss',  # generated from the company settings
    'test_assetsbundle/static/invalid_src/xml/file_not_found.xml',  # tests the error
}

IMPORT_RE = re.compile(
    r'''(?:^|[\s;}])(?:import|export)\s[^;'"]*?from\s*(['"])([^'"]+)\1'''
    r'''|(?:^|[\s;}(=])import\s*(['"])([^'"]+)\3'''
    r'''|\bimport\(\s*(['"])([^'"]+)\5\s*\)''',
    re.M,
)


def module_name(path):
    """`addons/web/static/src/core/x.js` -> `@web/core/x`,
    `addons/web/static/tests/core/x.test.js` -> `@web/../tests/core/x.test`"""
    for addons_dir in ADDONS_DIRS:
        try:
            rel = path.relative_to(addons_dir)
        except ValueError:
            continue
        addon, static, kind, *rest = rel.parts
        rest = '/'.join(rest)[: -len('.js')]
        return f'@{addon}/{rest}' if kind == 'src' else f'@{addon}/../{kind}/{rest}'
    return None


def module_path(name):
    """Inverse of module_name, None for modules outside of the repository."""
    m = re.match(r'@([\w-]+)/(.*)$', name)
    if not m:
        return None
    addon, rest = m.groups()
    for addons_dir in ADDONS_DIRS:
        if (addons_dir / addon).is_dir():
            if rest.startswith('../'):
                return addons_dir / addon / 'static' / f'{rest[3:]}.js'
            return addons_dir / addon / 'static' / 'src' / f'{rest}.js'
    return None


def resolve(spec, importer_name):
    if spec.startswith('.'):
        base = PurePosixPath(importer_name).parent
        parts = []
        for seg in f'{base}/{spec}'.split('/'):
            if seg == '..' and parts and parts[-1] not in ('..',) and not parts[-1].startswith('@'):
                parts.pop()
            elif seg not in ('', '.'):
                parts.append(seg)
        return '/'.join(parts)
    return spec


def js_files():
    for addons_dir in ADDONS_DIRS:
        for path in addons_dir.glob('*/static/*/**/*.js'):
            if '/static/lib/' not in str(path):
                yield path


def layer_of(name):
    if not name.startswith('@web/') or name.startswith('@web/../'):
        return None
    top = name[len('@web/'):].split('/')[0]
    for layer, tops in LAYERS:
        if top in tops:
            return layer
    return None


def check_imports(problems, verbose):
    count = 0
    for path in js_files():
        importer = module_name(path)
        text = path.read_text(errors='ignore')
        if '@odoo-module ignore' in text[:200]:
            continue
        # type imports of the JSDoc comments are not loaded
        text = re.sub(r'/\*.*?\*/|//[^\n]*', lambda m: '\n' * m.group().count('\n'), text, flags=re.S)
        for m in IMPORT_RE.finditer(text):
            spec = m.group(2) or m.group(4) or m.group(6)
            name = resolve(spec, importer)
            if not name.startswith('@') or name.startswith('@odoo/'):
                continue  # owl, hoot and other libraries
            target = module_path(name)
            count += 1
            if target is None:
                continue  # module of an addon that is not in the repository
            if not target.is_file():
                problems.append(f'{path.relative_to(REPO)}: missing module {name!r} (imported as {spec!r})')
                continue
            src, dst = layer_of(importer), layer_of(name)
            rel = name[len('@web/'):] if name.startswith('@web/') else None
            if src is not None and dst is not None and dst > src and rel not in SHARED:
                problems.append(f'{path.relative_to(REPO)}: {importer} (L{src}) imports {name} (L{dst})')
    # Odoo wrappers of the libraries declare their dependencies by name
    for addons_dir in ADDONS_DIRS:
        for path in addons_dir.glob('*/static/lib/**/odoo_module.js'):
            for deps in re.findall(r'odoo\.define\(\s*["\'][^"\']+["\']\s*,\s*\[([^\]]*)\]', path.read_text()):
                for name in re.findall(r'["\']([^"\']+)["\']', deps):
                    target = module_path(name)
                    count += 1
                    if target is not None and not target.is_file():
                        problems.append(f'{path.relative_to(REPO)}: missing module {name!r}')
    if verbose:
        print(f'{count} imports checked')  # noqa: T201


def check_assets(problems, verbose):
    count = 0
    for addons_dir in ADDONS_DIRS:
        for manifest in addons_dir.glob('*/__manifest__.py'):
            assets = ast.literal_eval(manifest.read_text()).get('assets') or {}
            for items in assets.values():
                for item in items:
                    paths = [item] if isinstance(item, str) else [p for p in item[1:] if isinstance(p, str)]
                    for p in paths:
                        p = p.lstrip('/')
                        if p in VIRTUAL_ASSETS:
                            continue
                        if '.' not in p.split('/')[-1] and '*' not in p:
                            continue  # bundle name, e.g. ('include', 'web._assets_core')
                        addon = p.split('/')[0]
                        base = next((d for d in ADDONS_DIRS if (d / addon).is_dir()), None)
                        if base is None:
                            continue
                        count += 1
                        if not glob.glob(str(base / p), recursive=True):
                            problems.append(f'{manifest.relative_to(REPO)}: no file matches {p!r}')
    if verbose:
        print(f'{count} asset paths checked')  # noqa: T201


def main():
    verbose = '--verbose' in sys.argv
    problems = []
    check_imports(problems, verbose)
    check_assets(problems, verbose)
    for problem in problems:
        print(problem)  # noqa: T201
    if verbose or problems:
        print(f'{len(problems)} problem(s)')  # noqa: T201
    return 1 if problems else 0


if __name__ == '__main__':
    sys.exit(main())
