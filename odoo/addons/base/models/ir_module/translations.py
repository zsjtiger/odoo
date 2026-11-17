# Part of Odoo. See LICENSE file for full copyright and licensing details.
"""The translations of the modules: the terms of the modules and of their resources."""

from odoo.modules.module import Manifest
from odoo.tools.text.translate import (
    TranslationImporter,
    get_datafile_translation_path,
    get_po_paths,
)

from .module import _logger

def _load_module_terms(self, modules, langs, overwrite=False):
    """ Load PO files of the given modules for the given languages. """
    # load i18n files
    translation_importer = TranslationImporter(self.env.cr, verbose=False)

    for module_name in modules:
        if not Manifest.for_addon(module_name, display_warning=False):
            continue
        for lang in langs:
            for po_path in get_po_paths(module_name, lang):
                _logger.info('module %s: loading translation file %s for language %s', module_name, po_path, lang)
                translation_importer.load_file(po_path, lang)
            for data_path in get_datafile_translation_path(module_name):
                translation_importer.load_file(data_path, lang, module=module_name)
            if lang != 'en_US' and lang not in translation_importer.imported_langs:
                _logger.info('module %s: no translation for language %s', module_name, lang)

    translation_importer.save(overwrite=overwrite)


def _load_non_installed_modules_manifest_terms(self, langs):
    """Load module manifest translations for all non-installed modules."""

    if not langs or (len(langs) == 1 and langs[0] in ('en_US', 'en')):
        return

    for module in self.search([('state', '!=', 'installed')]):
        manifest = Manifest.for_addon(module.name, display_warning=False)
        if not manifest:
            continue
        translations_by_field = manifest.get_translations(langs)
        if not translations_by_field:
            continue
        module.write(translations_by_field)


def _extract_resource_attachment_translations(self, module, lang):
    yield from ()
