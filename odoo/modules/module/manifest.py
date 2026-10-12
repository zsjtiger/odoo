"""The manifests of the modules: their parsing, their validation and their defaults, and the discovery of the modules."""

from __future__ import annotations

import ast
import copy
import functools
import logging
import os
import re
import typing
from collections import defaultdict
from collections.abc import Collection, Iterable, Mapping
from os.path import join as opj
import odoo.tools as tools
from odoo.tools.text.translate import get_po_paths, get_translations_for_references
import odoo.addons

if typing.TYPE_CHECKING:
    pass

from .dependencies import MissingDependency, check_python_external_dependency
from .versions import adapt_version, check_version

_logger = logging.getLogger('odoo.modules.module')


MODULE_NAME_RE = re.compile(r'^\w{1,256}$')


MANIFEST_NAMES = ['__manifest__.py']


README = ['README.rst', 'README.md', 'README.txt', 'README']


_DEFAULT_MANIFEST = {
    # Mandatory fields (with no defaults):
    # - author
    # - license
    # - name
    # Derived fields are computed in the Manifest class.
    'application': False,
    'bootstrap': False,  # web
    'assets': {},
    'auto_install': False,
    'category': 'Uncategorized',
    'cloc_exclude': [],
    'configurator_snippets': {},  # website themes
    'configurator_snippets_addons': {},  # website themes
    'countries': [],
    'data': [],
    'demo': [],
    'depends': [],
    'description': '',  # defaults to README file
    'external_dependencies': {},
    'iap_paid_service': False,
    'installable': True,
    'images': [],  # website
    'kpi_providers': [],
    'live_test_url': '',  # website themes
    'new_page_templates': {},  # website themes
    'other_files': [],
    'post_init_hook': '',
    'post_load': '',
    'pre_init_hook': '',
    'sequence': 100,
    'summary': '',
    'test': [],
    'theme_customizations': {},  # themes
    'uninstall_hook': '',
    'version': '1.0',
    'web': False,
    'website': '',
}


@typing.final
class Manifest(Mapping[str, typing.Any]):
    """The manifest data of a module."""

    def __init__(self, *, path: str, manifest_content: dict):
        assert os.path.isabs(path), "path of module must be absolute"
        self.path = path
        _, self.name = os.path.split(path)
        if not MODULE_NAME_RE.match(self.name):
            raise FileNotFoundError(f"Invalid module name: {self.name}")
        self.__manifest_content = manifest_content
        # Maps PO file paths to a dict of field names to translated strings.
        # e.g. {'/path/to/fr.po': {'description': 'Description en français', 'summary': 'Résumé en français'}}
        self.__manifest_translations: dict[str, dict[str, str]] = {}

    @property
    def addons_path(self) -> str:
        parent_path, name = os.path.split(self.path)
        assert name == self.name
        return parent_path

    @functools.cached_property
    def __manifest_cached(self) -> dict:
        """Parsed and validated manifest data from the file."""
        return _load_manifest(self.name, self.__manifest_content)

    @functools.cached_property
    def description(self):
        """The description of the module defaulting to the README file."""
        if (desc := self.__manifest_cached.get('description')):
            return desc
        for file_name in README:
            try:
                with tools.file_open(opj(self.path, file_name)) as f:
                    return f.read()
            except OSError:
                pass
        return ''

    @functools.cached_property
    def version(self):
        try:
            return self.__manifest_cached['version']
        except Exception:  # noqa: BLE001
            return adapt_version('1.0')

    @functools.cached_property
    def icon(self) -> str:
        return get_module_icon(self.name)

    @functools.cached_property
    def static_path(self) -> str | None:
        static_path = opj(self.path, 'static')
        manifest = self.__manifest_cached
        if (manifest['installable'] or manifest['assets']) and os.path.isdir(static_path):
            return static_path
        return None

    def get_translations(self, langs: Iterable[str]) -> dict[str, dict[str, str]]:
        """Get manifest translations for multiple languages.

        Parsing is cached per PO path to reuse work across related locales,
        e.g. ``fr_BE`` and ``fr_FR`` can share ``fr.po``.

        Returns a dictionary mapping field names to dictionaries of language codes to translated strings.
        For example:
        ```
        {
            'description': {
                'fr_FR': 'Description en français',
                'es_ES': 'Descripción en español',
            },
            'summary': {
                'fr_FR': 'Résumé en français',
                'es_ES': 'Resumen en español',
            },
        }
        ```
        """
        reference_to_field = {
            f'model:ir.module.module,description:base.module_{self.name}': 'description',
            f'model:ir.module.module,shortdesc:base.module_{self.name}': 'shortdesc',
            f'model:ir.module.module,summary:base.module_{self.name}': 'summary',
        }
        translations_by_field: dict[str, dict[str, str]] = defaultdict(dict)

        for lang in dict.fromkeys(langs):
            # fields_for_lang: dict[str, str] = {}
            for po_path in get_po_paths(self.name, lang):
                po_translations = self.__manifest_translations.get(po_path)
                if po_translations is None:
                    refs = get_translations_for_references(po_path, reference_to_field)
                    po_translations = {}
                    for ref, ref_translations in refs.items():
                        field_name = reference_to_field[ref]
                        po_translations[field_name] = list(ref_translations.values())[-1]
                    self.__manifest_translations[po_path] = po_translations
                if not po_translations:
                    continue
                for field_name, msgstr in po_translations.items():
                    translations_by_field[field_name][lang] = msgstr

        return dict(translations_by_field)

    def __getitem__(self, key: str):
        if key in ('description', 'icon', 'addons_path', 'version', 'static_path'):
            return getattr(self, key)
        return copy.deepcopy(self.__manifest_cached[key])

    def raw_value(self, key):
        return copy.deepcopy(self.__manifest_cached.get(key))

    def __iter__(self):
        manifest = self.__manifest_cached
        yield from manifest
        for key in ('description', 'icon', 'addons_path', 'version', 'static_path'):
            if key not in manifest:
                yield key

    def check_manifest_dependencies(self) -> None:
        """Check that the dependecies of the manifest are available.

        - Checking for external python dependencies
        - Checking binaries are available in PATH

        On missing dependencies, raise an error.
        """
        depends = self.get('external_dependencies')
        if not depends:
            return
        for pydep in depends.get('python', []):
            check_python_external_dependency(pydep)

        for binary in depends.get('bin', []):
            try:
                tools.find_in_path(binary)
            except OSError:
                msg = "Unable to find {dependency!r} in path"
                raise MissingDependency(msg, binary)

    def __bool__(self):
        return True

    def __len__(self):
        return sum(1 for _ in self)

    def __repr__(self):
        return f'Manifest({self.name})'

    # limit cache size because this may get called from any module with any input
    @staticmethod
    @functools.lru_cache(10_000)
    def _get_manifest_from_addons(module: str) -> Manifest | None:
        """Get the module's manifest from a name. Searching only in addons paths."""
        for adp in odoo.addons.__path__:
            if manifest := Manifest._from_path(opj(adp, module)):
                return manifest
        return None

    @staticmethod
    def for_addon(module_name: str, *, display_warning: bool = True) -> Manifest | None:
        """Get the module's manifest from a name.

        :param module: module's name
        :param display_warning: log a warning if the module is not found
        """
        if not MODULE_NAME_RE.match(module_name):
            # invalid module name
            return None
        if mod := Manifest._get_manifest_from_addons(module_name):
            return mod
        if display_warning:
            _logger.warning('module %s: manifest not found', module_name)
        return None

    @staticmethod
    def _from_path(path: str, env=None) -> Manifest | None:
        """Given a path, read the manifest file."""
        for manifest_name in MANIFEST_NAMES:
            try:
                with tools.file_open(opj(path, manifest_name), env=env) as f:
                    manifest_content = ast.literal_eval(f.read())
            except OSError:
                pass
            except Exception:  # noqa: BLE001
                _logger.debug("Failed to parse the manifest file at %r", path, exc_info=True)
            else:
                return Manifest(path=path, manifest_content=manifest_content)
        return None

    @staticmethod
    def all_addon_manifests() -> list[Manifest]:
        """Read all manifests in the addons paths."""
        modules: dict[str, Manifest] = {}
        for adp in odoo.addons.__path__:
            if not os.path.isdir(adp):
                _logger.warning("addons path is not a directory: %s", adp)
                continue
            for file_name in os.listdir(adp):
                if file_name in modules:
                    continue
                if mod := Manifest._from_path(opj(adp, file_name)):
                    assert file_name == mod.name
                    modules[file_name] = mod
        return sorted(modules.values(), key=lambda m: m.name)


def get_module_icon(module: str) -> str:
    """ Get the path to the module's icon. Invalid module names are accepted. """
    manifest = Manifest.for_addon(module, display_warning=False)
    if manifest and 'icon' in manifest.__dict__:
        # we have a value in the cached property
        return manifest.icon
    fpath = ''
    if manifest:
        fpath = manifest.raw_value('icon') or ''
        fpath = fpath.lstrip('/')
    if not fpath:
        fpath = f"{module}/static/description/icon.png"
    try:
        tools.file_path(fpath)
        return "/" + fpath
    except FileNotFoundError:
        return "/base/static/description/icon.png"


def _load_manifest(module: str, manifest_content: dict) -> dict:
    """ Load and validate the module manifest.

    Return a new dictionary with cleaned and validated keys.
    """

    manifest = copy.deepcopy(_DEFAULT_MANIFEST)
    manifest.update(manifest_content)

    if not manifest.get('author'):
        # Altought contributors and maintainer are not documented, it is
        # not uncommon to find them in manifest files, use them as
        # alternative.
        author = manifest.get('contributors') or manifest.get('maintainer') or ''
        manifest['author'] = str(author)
        _logger.warning("Missing `author` key in manifest for %r, defaulting to %r", module, str(author))

    if not manifest.get('license'):
        manifest['license'] = 'LGPL-3'
        _logger.warning("Missing `license` key in manifest for %r, defaulting to LGPL-3", module)

    if module == 'base':
        manifest['depends'] = []
    elif not manifest['depends']:
        # prevent the hack `'depends': []` except 'base' module
        manifest['depends'] = ['base']

    depends = manifest['depends']
    assert isinstance(depends, Collection)

    # auto_install is either `False` (by default) in which case the module
    # is opt-in, either a list of dependencies in which case the module is
    # automatically installed if all dependencies are (special case: [] to
    # always install the module), either `True` to auto-install the module
    # in case all dependencies declared in `depends` are installed.
    if isinstance(manifest['auto_install'], Iterable):
        manifest['auto_install'] = auto_install_set = set(manifest['auto_install'])
        non_dependencies = auto_install_set.difference(depends)
        assert not non_dependencies, (
            "auto_install triggers must be dependencies,"
            f" found non-dependencies [{', '.join(non_dependencies)}] for module {module}"
        )
    elif manifest['auto_install']:
        manifest['auto_install'] = set(depends)

    try:
        manifest['version'] = adapt_version(str(manifest['version']))
    except ValueError as e:
        if manifest['installable']:
            raise ValueError(f"Module {module}: invalid manifest") from e
    if manifest['installable'] and not check_version(str(manifest['version']), should_raise=False):
        _logger.warning("The module %s has an incompatible version, setting installable=False", module)
        manifest['installable'] = False

    return manifest


def get_manifest(module: str, mod_path: str | None = None) -> Mapping[str, typing.Any]:
    """
    Get the module manifest.

    :param str module: The name of the module (sale, purchase, ...).
    :param Optional[str] mod_path: The optional path to the module on
        the file-system. If not set, it is determined by scanning the
        addons-paths.
    :returns: The module manifest as a dict or an empty dict
        when the manifest was not found.
    """
    if mod_path:
        mod = Manifest._from_path(mod_path)
        if mod and mod.name != module:
            raise ValueError(f"Invalid path for module {module}: {mod_path}")
    else:
        mod = Manifest.for_addon(module, display_warning=False)
    return mod if mod is not None else {}


def get_modules() -> list[str]:
    """Get the list of module names that can be loaded.
    """
    return [m.name for m in Manifest.all_addon_manifests()]
