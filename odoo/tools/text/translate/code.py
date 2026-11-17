"""The translations of the code: the translations of the Python and JavaScript terms of the modules."""

from __future__ import annotations

import logging
from odoo.tools.misc import file_open, frozendict
from .base import JAVASCRIPT_TRANSLATION_COMMENT, PYTHON_TRANSLATION_COMMENT, get_iso_codes
from .files import translation_file_reader

from .po import get_po_paths

_logger = logging.getLogger('odoo.tools.text.translate')


class CodeTranslations:
    def __init__(self):
        # {(module_name, lang): {src: value}}
        self.python_translations = {}
        # {(module_name, lang): {'message': [{'id': src, 'string': value}]}
        self.web_translations = {}

    @staticmethod
    def _read_code_translations_file(fileobj, filter_func):
        """ read and return code translations from fileobj with filter filter_func

        :param func filter_func: a filter function to drop unnecessary code translations
        """
        # current, we assume the fileobj is from the source code, which only contains the translation for the current module
        # don't use it in the import logic
        translations = {}
        fileobj.seek(0)
        reader = translation_file_reader(fileobj, fileformat='po')
        for row in reader:
            if row.get('type') == 'code' and row.get('src') and filter_func(row):
                translations[row['src']] = row['value']
        return translations

    @staticmethod
    def _get_code_translations(module_name, lang, filter_func):
        po_paths = get_po_paths(module_name, lang)
        translations = {}
        for po_path in po_paths:
            try:
                with file_open(po_path, mode='rb') as fileobj:
                    p = CodeTranslations._read_code_translations_file(fileobj, filter_func)
                translations.update(p)
            except IOError:
                iso_lang = get_iso_codes(lang)
                filename = '[lang: %s][format: %s]' % (iso_lang or 'new', 'po')
                _logger.exception("couldn't read translation file %s", filename)
        return translations

    def _load_python_translations(self, module_name, lang):
        def filter_func(row):
            return row.get('value') and PYTHON_TRANSLATION_COMMENT in row['comments']
        translations = CodeTranslations._get_code_translations(module_name, lang, filter_func)
        self.python_translations[module_name, lang] = frozendict(translations)

    def _load_web_translations(self, module_name, lang):
        def filter_func(row):
            return row.get('value') and JAVASCRIPT_TRANSLATION_COMMENT in row['comments']
        translations = CodeTranslations._get_code_translations(module_name, lang, filter_func)
        self.web_translations[module_name, lang] = frozendict({
            "messages": tuple(
                frozendict({"id": src, "string": value})
                for src, value in translations.items())
        })

    def get_python_translations(self, module_name, lang):
        if (module_name, lang) not in self.python_translations:
            self._load_python_translations(module_name, lang)
        return self.python_translations[(module_name, lang)]

    def get_web_translations(self, module_name, lang):
        if (module_name, lang) not in self.web_translations:
            self._load_web_translations(module_name, lang)
        return self.web_translations[(module_name, lang)]


code_translations = CodeTranslations()
