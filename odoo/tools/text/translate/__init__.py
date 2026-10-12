# Part of Odoo. See LICENSE file for full copyright and licensing details.
# ruff: noqa: F401
"""Translation of Odoo: the lazy translations, the translation of the XML and HTML fields, the stored translations, the extraction and the files. The names are re-exported here."""

from .base import JAVASCRIPT_TRANSLATION_COMMENT, LazyGettext, LazyTranslate, PYTHON_TRANSLATION_COMMENT, ParsedTranslation, StoredTranslations, _, _get_cr, _get_frame, _get_lang, _get_translation_source, _get_uid, _lt, _sub_replacement, adapt_translated_field_value, get_iso_codes, get_text_alias, get_text_content, get_translated_module, get_translation, is_text, mark_as_copy, parse_xmlid, quote, re_escaped_char, re_escaped_replacements, unquote
from .html import FIELD_TRANSLATE, FORMAT_REGEX, MODIFIER_ATTRS, OWL_TRANSLATED_ATTRS, SKIPPED_ELEMENTS, TRANSLATED_ATTRS, TRANSLATED_ELEMENTS, _HTML_PARSER, avoid_pattern, html_term_converter, html_translate, is_translatable_attrib, is_translatable_attrib_text, is_translatable_attrib_value, parse_html, parse_xml, serialize_html, serialize_xml, space_pattern, translate_format_string_expression, translate_xml_node, xml_term_adapter, xml_term_converter, xml_translate
from .extract import _extract_translatable_qweb_terms, babel_extract_qweb, extract_formula_terms, extract_spreadsheet_terms, is_meaningful_term
from .files import CSVDataFileReader, CSVFileReader, CSVFileWriter, PoFileReader, PoFileWriter, TarFileWriter, TranslationFileWriter, XMLDataFileReader, _writer, translation_file_reader
from .code import CodeTranslations, code_translations
from .export import trans_export, trans_export_records
from .importer import DeepDefaultDict, TranslationImporter, _get_translation_upgrade_queries
from .languages import get_base_langs, get_locales, load_language, resetlocale
from .po import CHARSET_REGEX, get_datafile_translation_path, get_po_paths, get_translations_for_references
from .readers import ImdInfo, TranslationModuleReader, TranslationReader, TranslationRecordReader

__all__ = [
    'LazyTranslate',
    '_',
    'get_iso_codes',
    'html_translate',
    'mark_as_copy',
    'xml_translate',
]
