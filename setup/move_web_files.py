#!/usr/bin/env python3
# Part of Odoo. See LICENSE file for full copyright and licensing details.
"""Reorganize addons/web/static/src according to setup/web_layout.py.

    setup/move_web_files.py PHASE         move the files of a phase (W1, W2...)
    setup/move_web_files.py --port DIR..  rewrite the references to the web
                                          files in other addons (all phases)

Moving a file of web/static/src changes its JS module name (@web/<path>)
and its asset path (web/static/src/<path>). The script moves the files with
`git mv`, the matching test files of web/static/tests too, and rewrites:

- the module names and asset paths in every text file of the repository,
- the relative imports (./x, ../y) of the JS files whose location or whose
  target's location changes.
"""
import os
import re
import subprocess
import sys
from pathlib import Path, PurePosixPath

sys.path.insert(0, str(Path(__file__).resolve().parent))
import web_layout  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
SRC = 'addons/web/static/src'
TESTS = 'addons/web/static/tests'
TEXT_SUFFIXES = {'.js', '.ts', '.xml', '.py', '.html', '.scss', '.css', '.json', '.md', '.po', '.pot', '.csv', '.txt', '.rst'}
# files whose `@web/...` strings are made-up names, not modules
EXCLUDED = {'addons/web/tests/test_js.py'}
RELATIVE_RE = re.compile(r'''(\bfrom\s*|\bimport\s*\(\s*|\bimport\s+)(['"])(\.{1,2}/[^'"]+)\2''')


def strip_js(path):
    return path[:-3] if path.endswith('.js') else path


def file_moves(dir_moves):
    """{old repo path: new repo path} of every file to move."""
    result = {}
    for root, rel_moves in ((SRC, dir_moves), (TESTS, test_moves(dir_moves))):
        for old, new in rel_moves.items():
            old_path = REPO / root / old
            if old_path.is_dir():
                for f in sorted(old_path.rglob('*')):
                    if f.is_file():
                        rel = f.relative_to(old_path).as_posix()
                        result[f'{root}/{old}/{rel}'] = f'{root}/{new}/{rel}'
            elif old_path.is_file():
                result[f'{root}/{old}'] = f'{root}/{new}'
    return result


def test_moves(dir_moves):
    """The tests of web mirror its sources: move them along."""
    result = {}
    for old, new in dir_moves.items():
        if (REPO / TESTS / old).is_dir():
            result[old] = new
        elif old.endswith('.js') and (REPO / TESTS / f'{old[:-3]}.test.js').is_file():
            result[f'{old[:-3]}.test.js'] = f'{new[:-3]}.test.js'
    return result


def replacements(dir_moves):
    """[(old string, new string, is_folder)] for module names and asset paths."""
    pairs = []
    for old, new in dir_moves.items():
        is_dir = (REPO / SRC / old).is_dir()
        pairs.append((f'@web/{strip_js(old)}', f'@web/{strip_js(new)}', is_dir))
        pairs.append((f'web/static/src/{old}', f'web/static/src/{new}', is_dir))
    for old, new in test_moves(dir_moves).items():
        is_dir = (REPO / TESTS / old).is_dir()
        pairs.append((f'@web/../tests/{strip_js(old)}', f'@web/../tests/{strip_js(new)}', is_dir))
        pairs.append((f'web/static/tests/{old}', f'web/static/tests/{new}', is_dir))
    return pairs


def compile_replacements(pairs):
    # a folder is followed by "/" or the end of the string, a file only by the end
    alternatives = []
    mapping = {}
    for old, new, is_dir in sorted(pairs, key=lambda p: -len(p[0])):
        end = r'''(?=[/'"`\s,)*:?]|$)''' if is_dir else r'''(?=['"`\s,):?]|$)'''
        alternatives.append(re.escape(old) + end)
        mapping[old] = new
    regex = re.compile(r'(?<![\w-])(?:' + '|'.join(alternatives) + ')', re.M)

    def apply(text):
        return regex.sub(lambda m: mapping[m.group(0)], text)
    return apply


def text_files(roots):
    for root in roots:
        for path in Path(root).rglob('*'):
            rel = path.relative_to(REPO).as_posix() if path.is_relative_to(REPO) else str(path)
            if not path.is_file() or path.suffix not in TEXT_SUFFIXES or '/.git/' in f'/{rel}':
                continue
            if '/static/lib/' in f'/{rel}' and path.suffix != '.html' and path.name != 'odoo_module.js':
                continue  # third-party code, but its HTML pages and Odoo wrappers refer to web files
            if rel in EXCLUDED:
                continue
            yield rel, path


def module_dir(repo_path):
    """Directory of a JS file, in module terms: the folder relative imports
    are resolved against."""
    return PurePosixPath(repo_path).parent


def rewrite_relative_imports(text, old_path, new_path, files):
    old_dir, new_dir = module_dir(old_path), module_dir(new_path)

    def fix(m):
        prefix, quote, spec = m.groups()
        target_old = os.path.normpath(f'{old_dir}/{spec}')
        ext = '' if PurePosixPath(target_old).suffix else '.js'
        target_new = files.get(target_old + ext, target_old + ext)
        if target_new == target_old + ext and new_dir == old_dir:
            return m.group(0)
        target_new = target_new[: len(target_new) - len(ext)] if ext else target_new
        rel = os.path.relpath(target_new, new_dir)
        if not rel.startswith('.'):
            rel = f'./{rel}'
        return f'{prefix}{quote}{rel}{quote}'
    return RELATIVE_RE.sub(fix, text)


def run_phase(phase):
    dir_moves = web_layout.moves(phase)
    files = file_moves(dir_moves)
    apply = compile_replacements(replacements(dir_moves))
    changed = 0
    for rel, path in text_files([REPO / 'addons', REPO / 'odoo', REPO / 'setup']):
        if rel.startswith('setup/') and path.name in ('web_layout.py', 'move_web_files.py'):
            continue
        text = path.read_text(errors='surrogateescape')
        new = apply(text)
        if path.suffix == '.js':
            new = rewrite_relative_imports(new, rel, files.get(rel, rel), files)
        if new != text:
            path.write_text(new, errors='surrogateescape')
            changed += 1
    for old, new in files.items():
        (REPO / new).parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(['git', 'mv', old, new], cwd=REPO, check=True)
    for root in (SRC, TESTS):  # remove the folders left empty
        for d in sorted((REPO / root).rglob('*'), key=lambda p: -len(p.parts)):
            if d.is_dir() and not any(d.iterdir()):
                d.rmdir()
    print(f'{phase}: {len(dir_moves)} entries, {len(files)} files moved, {changed} files rewritten')  # noqa: T201


def port(dirs):
    # the addon still refers to the former layout: apply all the moves at once
    dir_moves = web_layout.moves()
    apply = compile_replacements(
        [(f'@web/{strip_js(o)}', f'@web/{strip_js(n)}', '.' not in o.rsplit('/', 1)[-1]) for o, n in dir_moves.items()]
        + [(f'web/static/src/{o}', f'web/static/src/{n}', '.' not in o.rsplit('/', 1)[-1]) for o, n in dir_moves.items()]
    )
    changed = 0
    for rel, path in text_files([Path(d).resolve() for d in dirs]):
        text = path.read_text(errors='surrogateescape')
        new = apply(text)
        if new != text:
            path.write_text(new, errors='surrogateescape')
            changed += 1
    print(f'{changed} files rewritten')  # noqa: T201


if __name__ == '__main__':
    if sys.argv[1:2] == ['--port']:
        port(sys.argv[2:])
    elif len(sys.argv) == 2 and sys.argv[1] in web_layout.PHASES:
        run_phase(sys.argv[1])
    else:
        sys.exit(__doc__)
