# Part of Odoo. See LICENSE file for full copyright and licensing details.
"""Paths and files of the server: the addons files, the temporary directories and the binaries."""

from __future__ import annotations
import os
import sys
import tempfile
import typing
from contextlib import contextmanager
from odoo.tools.config import config
from odoo.tools.system.which import which

if typing.TYPE_CHECKING:
    from odoo.api import Environment


def find_in_path(name):
    path = os.environ.get('PATH', os.defpath).split(os.pathsep)
    if config.get('bin_path') and config['bin_path'] != 'None':
        path.append(config['bin_path'])
    return which(name, path=os.pathsep.join(path))


def file_path(file_path: str, filter_ext: tuple[str, ...] = ('',), env: Environment | None = None, *, check_exists: bool = True) -> str:
    """Verify that a file exists under a known `addons_path` directory and return its full path.

    Examples::

    >>> file_path('hr')
    >>> file_path('hr/static/description/icon.png')
    >>> file_path('hr/static/description/icon.png', filter_ext=('.png', '.jpg'))

    :param str file_path: absolute file path, or relative path within any `addons_path` directory
    :param list[str] filter_ext: optional list of supported extensions (lowercase, with leading dot)
    :param env: optional environment, required for a file path within a temporary directory
        created using `file_open_temporary_directory()`
    :param check_exists: check that the file exists (default: True)
    :return: the absolute path to the file
    :raise FileNotFoundError: if the file is not found under the known `addons_path` directories
    :raise ValueError: if the file doesn't have one of the supported extensions (`filter_ext`)
    """
    import odoo.addons  # noqa: PLC0415
    is_abs = os.path.isabs(file_path)
    normalized_path = os.path.normpath(os.path.normcase(file_path))

    if filter_ext and not normalized_path.lower().endswith(filter_ext):
        raise ValueError("Unsupported file: " + file_path)

    # ignore leading 'addons/' if present, it's the final component of root_path, but
    # may sometimes be included in relative paths
    normalized_path = normalized_path.removeprefix('addons' + os.sep)

    # if path is relative and represents a loaded module, accept only the
    # __path__ for that module; otherwise, search in all accepted paths
    file_path_split = normalized_path.split(os.path.sep)
    if not is_abs and (module := sys.modules.get(f'odoo.addons.{file_path_split[0]}')):
        addons_paths = list(map(os.path.dirname, module.__path__))
    else:
        root_path = os.path.abspath(config.root_path)
        temporary_paths = env.transaction._Transaction__file_open_tmp_paths if env else []
        addons_paths = [*odoo.addons.__path__, root_path, *temporary_paths]

    for addons_dir in addons_paths:
        # final path sep required to avoid partial match
        parent_path = os.path.normpath(os.path.normcase(addons_dir)) + os.sep
        if is_abs:
            fpath = normalized_path
        else:
            fpath = os.path.normpath(os.path.join(parent_path, normalized_path))
        if fpath.startswith(parent_path) and (
            # we check existence when asked or we have multiple paths to check
            # (there is one possibility for absolute paths)
            (not check_exists and (is_abs or len(addons_paths) == 1))
            or os.path.exists(fpath)
        ):
            return fpath

    raise FileNotFoundError("File not found: " + file_path)


def file_open(name: str, mode: str = "r", filter_ext: tuple[str, ...] = (), env: Environment | None = None):
    """Open a file from within the addons_path directories, as an absolute or relative path.

    Examples::

        >>> file_open('hr/static/description/icon.png')
        >>> file_open('hr/static/description/icon.png', filter_ext=('.png', '.jpg'))
        >>> with file_open('/opt/odoo/addons/hr/static/description/icon.png', 'rb') as f:
        ...     contents = f.read()

    :param name: absolute or relative path to a file located inside an addon
    :param mode: file open mode, as for `open()`
    :param list[str] filter_ext: optional list of supported extensions (lowercase, with leading dot)
    :param env: optional environment, required to open a file within a temporary directory
        created using `file_open_temporary_directory()`
    :return: file object, as returned by `open()`
    :raise FileNotFoundError: if the file is not found under the known `addons_path` directories
    :raise ValueError: if the file doesn't have one of the supported extensions (`filter_ext`)
    """
    path = file_path(name, filter_ext=filter_ext, env=env, check_exists=False)
    encoding = None
    if 'b' not in mode:
        # Force encoding for text mode, as system locale could affect default encoding,
        # even with the latest Python 3 versions.
        # Note: This is not covered by a unit test, due to the platform dependency.
        #       For testing purposes you should be able to force a non-UTF8 encoding with:
        #         `sudo locale-gen fr_FR; LC_ALL=fr_FR.iso8859-1 python3 ...'
        # See also PEP-540, although we can't rely on that at the moment.
        encoding = "utf-8"
    if any(m in mode for m in ('w', 'x', 'a')) and not os.path.isfile(path):
        # Don't let create new files
        raise FileNotFoundError(f"Not a file: {path}")
    return open(path, mode, encoding=encoding)


@contextmanager
def file_open_temporary_directory(env: Environment):
    """Create and return a temporary directory added to the directories `file_open` is allowed to read from.

    `file_open` will be allowed to open files within the temporary directory
    only for environments of the same transaction than `env`.
    Meaning, other transactions/requests from other users or even other databases
    won't be allowed to open files from this directory.

    Examples::

        >>> with odoo.tools.file_open_temporary_directory(self.env) as module_dir:
        ...    with zipfile.ZipFile('foo.zip', 'r') as z:
        ...        z.extract('foo/__manifest__.py', module_dir)
        ...    with odoo.tools.file_open('foo/__manifest__.py', env=self.env) as f:
        ...        manifest = f.read()

    :param env: environment for which the temporary directory is created.
    :return: the absolute path to the created temporary directory
    """
    with tempfile.TemporaryDirectory() as module_dir:
        try:
            env.transaction._Transaction__file_open_tmp_paths.append(module_dir)
            yield module_dir
        finally:
            env.transaction._Transaction__file_open_tmp_paths.remove(module_dir)
