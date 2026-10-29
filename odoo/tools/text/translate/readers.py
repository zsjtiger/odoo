"""Readers of the translations: the terms of the modules, of the records and of the external ids of the translations."""

from __future__ import annotations

import fnmatch
import logging
import os
import re
from collections import defaultdict, namedtuple
from os.path import join
from babel.messages import extract
from odoo.tools.config import config
from odoo.tools.misc import file_open
from odoo.tools.sql import SQL
from .base import JAVASCRIPT_TRANSLATION_COMMENT, PYTHON_TRANSLATION_COMMENT
from .stored import StoredTranslations
from .extract import is_meaningful_term
from .files import translation_file_reader

from .code import code_translations
from .po import get_datafile_translation_path

_logger = logging.getLogger('odoo.tools.text.translate')


ImdInfo = namedtuple('ExternalId', ['name', 'model', 'res_id', 'module'])


class TranslationReader:
    def __init__(self, cr, lang=None):
        self._cr = cr
        self._lang = lang or 'en_US'
        from odoo import api  # noqa: PLC0415
        self.env = api.Environment(cr, api.SUPERUSER_ID, {})
        self._to_translate = []

    def __bool__(self):
        return bool(self._to_translate)

    def __iter__(self):
        for module, source, name, res_id, ttype, comments, _record_id, value in self._to_translate:
            yield (module, ttype, name, res_id, source, value, comments)

    def _push_translation(self, module, ttype, name, res_id, source, comments=None, record_id=None, value=None):
        """ Insert a translation that will be used in the file generation
        In po file will create an entry
        #: <ttype>:<name>:<res_id>
        #, <comment>
        msgid "<source>"
        record_id is the database id of the record being translated
        """
        if is_meaningful_term(source):
            self._to_translate.append((module, source, name, res_id, ttype, tuple(comments or ()), record_id, value))

    def _export_imdinfo(self, model: str, imd_per_id: dict[int, ImdInfo]):
        records = self._get_translatable_records(imd_per_id.values())
        if not records:
            return

        env = records.env
        for record in records.with_context(check_translations=True):
            export_module = record.name if model == 'ir.module.module' else imd_per_id[record.id].module
            xml_module = imd_per_id[record.id].module
            xml_name = "%s.%s" % (xml_module, imd_per_id[record.id].name)
            for field_name, field in record._fields.items():
                # ir_actions_actions.name is filtered because unlike other inherited fields,
                # this field is inherited as postgresql inherited columns.
                # From our business perspective, the parent column is no need to be translated,
                # but it is need to be set to jsonb column, since the child columns need to be translated
                # And export the parent field may make one value to be translated twice in transifex
                #
                # Some ir_model_fields.field_description are filtered
                # because their fields have falsy attribute export_string_translation
                if (
                        not (field.translate and field.store)
                        or str(field) == 'ir.actions.actions.name'
                        or (str(field) == 'ir.model.fields.field_description'
                            and not env[record.model]._fields[record.name].export_string_translation)
                ):
                    continue
                name = model + "," + field_name
                value_en = record[field_name] or ''
                value_lang = record.with_context(lang=self._lang)[field_name] or ''
                trans_type = 'model_terms' if callable(field.translate) else 'model'
                try:
                    translation_dictionary = StoredTranslations._get_translation_dictionary(field, value_en, {self._lang: value_lang})
                except Exception:
                    _logger.exception("Failed to extract terms from %s %s", xml_name, name)
                    continue
                for term_en, term_langs in translation_dictionary.items():
                    term_lang = term_langs.get(self._lang)
                    self._push_translation(export_module, trans_type, name, xml_name, term_en, record_id=record.id, value=term_lang if term_lang != term_en else '')

    def _get_translatable_records(self, imd_records):
        """ Filter the records that are translatable

        A record is considered as untranslatable if:
        - it does not exist
        - the model is flagged with _translate=False
        - it is a field of a model flagged with _translate=False
        - it is a selection of a field of a model flagged with _translate=False

        :param records: a list of namedtuple ImdInfo belonging to the same model
        """
        model = next(iter(imd_records)).model
        if model not in self.env:
            _logger.error("Unable to find object %r", model)
            return self.env["_unknown"].browse()

        if not self.env[model]._translate:
            return self.env[model].browse()

        res_ids = [r.res_id for r in imd_records]
        records = self.env[model].browse(res_ids).exists()
        if len(records) < len(res_ids):
            missing_ids = set(res_ids) - set(records.ids)
            missing_records = [f"{r.module}.{r.name}" for r in imd_records if r.res_id in missing_ids]
            _logger.warning("Unable to find records of type %r with external ids %s", model, ', '.join(missing_records))
            if not records:
                return records

        if model == 'ir.model.fields.selection':
            fields = defaultdict(list)
            for selection in records:
                fields[selection.field_id] = selection
            for field, selection in fields.items():
                field_name = field.name
                field_model = self.env.get(field.model)
                if (field_model is None or not field_model._translate or
                        field_name not in field_model._fields):
                    # the selection is linked to a model with _translate=False, remove it
                    records -= selection
        elif model == 'ir.model.fields':
            for field in records:
                field_name = field.name
                field_model = self.env.get(field.model)
                if (field_model is None or not field_model._translate or
                        field_name not in field_model._fields):
                    # the field is linked to a model with _translate=False, remove it
                    records -= field

        return records


class TranslationRecordReader(TranslationReader):
    """ Retrieve translations for specified records, the reader will
    1. create external ids for records without external ids
    2. export translations for stored translated and inherited translated fields
    :param cr: cursor to database to export
    :param model_name: model_name for the records to export
    :param ids: ids of the records to export
    :param field_names: field names to export, if not set, export all translatable fields
    :param lang: language code to retrieve the translations retrieve source terms only if not set
    """
    def __init__(self, cr, model_name, ids, field_names=None, lang=None):
        super().__init__(cr, lang)
        self._records = self.env[model_name].browse(ids)
        self._field_names = field_names or list(self._records._fields.keys())

        self._export_translatable_records(self._records, self._field_names)

    def _export_translatable_records(self, records, field_names):
        """ Export translations of all stored/inherited translated fields. Create external id if needed. """
        if not records:
            return

        fields = records._fields

        if records._inherits:
            inherited_fields = defaultdict(list)
            for field_name in field_names:
                field = records._fields[field_name]
                if field.translate and not field.store and field.inherited_field:
                    inherited_fields[field.inherited_field.model_name].append(field_name)
            for parent_mname, parent_fname in records._inherits.items():
                if parent_mname in inherited_fields:
                    self._export_translatable_records(records[parent_fname], inherited_fields[parent_mname])

        if not any(fields[field_name].translate and fields[field_name].store for field_name in field_names):
            return

        records._ensure_xml_id()

        model_name = records._name
        query = """SELECT min(concat(module, '.', name)), res_id
                             FROM ir_model_data
                            WHERE model = %s
                              AND res_id = ANY(%s)
                         GROUP BY model, res_id"""

        self._cr.execute(query, (model_name, records.ids))

        imd_per_id = {
            res_id: ImdInfo((tmp := module_xml_name.split('.', 1))[1], model_name, res_id, tmp[0])
            for module_xml_name, res_id in self._cr.fetchall()
        }

        self._export_imdinfo(model_name, imd_per_id)


class TranslationModuleReader(TranslationReader):
    """ Retrieve translated records per module

    :param cr: cursor to database to export
    :param modules: list of modules to filter the exported terms, can be ['all']
                    records with no external id are always ignored
    :param lang: language code to retrieve the translations
                 retrieve source terms only if not set
    """

    def __init__(self, cr, modules=None, lang=None):
        super().__init__(cr, lang)
        self._modules = modules or ['all']
        import odoo.addons  # noqa: PLC0415
        self._path_list = [(path, True) for path in odoo.addons.__path__]
        self._installed_modules = [
            m['name']
            for m in self.env['ir.module.module'].search_read([('state', '=', 'installed')], fields=['name'])
        ]

        self._export_translatable_records()
        self._export_translatable_resources()

    def _export_translatable_records(self):
        """ Export translations of all translated records having an external id """
        modules = self._installed_modules if 'all' in self._modules else list(self._modules)
        xml_defined = set()
        for module in modules:
            for filepath in get_datafile_translation_path(module):
                fileformat = os.path.splitext(filepath)[-1][1:].lower()
                with file_open(filepath, mode='rb') as source:
                    for entry in translation_file_reader(source, fileformat=fileformat, module=module):
                        xml_defined.add((entry['imd_model'], module, entry['imd_name']))

        manifest_xmlids = [f'module_{module}' for module in modules]
        imd_data = self.env.execute_query(SQL("""
            SELECT min(name), model, res_id, module
              FROM (
                    SELECT name, model, res_id, module
                      FROM ir_model_data
                     WHERE module = ANY(%(modules)s)
                       AND model != 'ir.module.module'

                    UNION ALL

                    SELECT name, model, res_id, module
                      FROM ir_model_data
                     WHERE model = 'ir.module.module'
                       AND module = 'base'
                       AND name = ANY(%(manifest_xmlids)s)
                   ) AS imd
          GROUP BY model, res_id, module
        """, modules=modules, manifest_xmlids=manifest_xmlids))

        records_per_model = defaultdict(dict)
        for (imd_name, model, res_id, module) in imd_data:
            if model != 'ir.module.module' and (model, module, imd_name) in xml_defined:
                continue
            records_per_model[model][res_id] = ImdInfo(imd_name, model, res_id, module)

        for model, imd_per_id in records_per_model.items():
            self._export_imdinfo(model, imd_per_id)

    def _get_module_from_path(self, path):
        dirname = os.path.join(os.path.dirname(path), '')
        best_mp = max((
            mpf for mp, rec in self._path_list
            if rec and (mpf := os.path.join(mp, '')) and path.startswith(mpf) and dirname != mpf
        ), key=len, default='')

        if best_mp:
            path = path[len(best_mp):]
            return path.split(os.path.sep)[0]
        return 'base'  # files that are not in a module are considered as being in 'base' module

    def _verified_module_filepaths(self, fname, path, root):
        fabsolutepath = join(root, fname)
        frelativepath = fabsolutepath[len(path):]
        display_path = "addons%s" % frelativepath
        module = self._get_module_from_path(fabsolutepath)
        if ('all' in self._modules or module in self._modules) and module in self._installed_modules:
            if os.path.sep != '/':
                display_path = display_path.replace(os.path.sep, '/')
            return module, fabsolutepath, frelativepath, display_path
        return None, None, None, None

    def _babel_extract_terms(self, fname, path, root, extract_method='odoo.tools.babel:extract_python', trans_type='code',
                               extra_comments=None, extract_keywords={'_': None}):

        module, fabsolutepath, _, display_path = self._verified_module_filepaths(fname, path, root)
        if not module:
            return
        extra_comments = extra_comments or []
        src_file = file_open(fabsolutepath, 'rb')
        options = {}
        if 'python' in extract_method:
            options['encoding'] = 'UTF-8'
            translations = code_translations.get_python_translations(module, self._lang)
        else:
            translations = code_translations.get_web_translations(module, self._lang)
            translations = {tran['id']: tran['string'] for tran in translations['messages']}
        try:
            for extracted in extract.extract(extract_method, src_file, keywords=extract_keywords, options=options):
                # Babel 0.9.6 yields lineno, message, comments
                # Babel 1.3 yields lineno, message, comments, context
                lineno, message, comments = extracted[:3]
                value = translations.get(message, '')
                self._push_translation(module, trans_type, display_path, lineno,
                                       message, comments + extra_comments, value=value)
        except Exception:
            _logger.exception("Failed to extract terms from %s", fabsolutepath)
        finally:
            src_file.close()

    def _export_translatable_resources(self):
        """ Export translations for static terms

        This will include:
        - the python strings marked with _() or _lt()
        - the javascript strings marked with _t() inside static/src/js/
        - the strings inside Qweb files inside static/src/xml/
        - the spreadsheet data files
        """

        # Also scan these non-addon paths
        for bin_path in ['orm', 'osv', 'report', 'modules', 'service', 'tools']:
            self._path_list.append((os.path.join(config.root_path, bin_path), True))
        # non-recursive scan for individual files in root directory but without
        # scanning subdirectories that may contain addons
        self._path_list.append((config.root_path, False))
        _logger.debug("Scanning modules at paths: %s", self._path_list)

        spreadsheet_files_regex = re.compile(r".*_dashboard(\.osheet)?\.json$")

        for (path, recursive) in self._path_list:
            _logger.debug("Scanning files of modules at %s", path)
            for root, _dummy, files in os.walk(path, followlinks=True):
                for fname in fnmatch.filter(files, '*.py'):
                    self._babel_extract_terms(fname, path, root, 'odoo.tools.babel:extract_python',
                                              extra_comments=[PYTHON_TRANSLATION_COMMENT],
                                              extract_keywords={'_': None, '_lt': None})
                if fnmatch.fnmatch(root, '*/static/src*'):
                    # Javascript source files
                    for fname in fnmatch.filter(files, '*.js'):
                        self._babel_extract_terms(fname, path, root, 'odoo.tools.babel:extract_javascript',
                                                  extra_comments=[JAVASCRIPT_TRANSLATION_COMMENT],
                                                  extract_keywords={'_t': None})
                    # QWeb template files
                    for fname in fnmatch.filter(files, '*.xml'):
                        self._babel_extract_terms(fname, path, root, 'odoo.tools.text.translate:babel_extract_qweb',
                                                  extra_comments=[JAVASCRIPT_TRANSLATION_COMMENT])
                if fnmatch.fnmatch(root, '*/data/*'):
                    for fname in filter(spreadsheet_files_regex.match, files):
                        self._babel_extract_terms(fname, path, root, 'odoo.tools.text.translate:extract_spreadsheet_terms',
                                                  extra_comments=[JAVASCRIPT_TRANSLATION_COMMENT])
                if not recursive:
                    # due to topdown, first iteration is in first level
                    break

        IrModuleModule = self.env['ir.module.module']
        for module in self._modules:
            for translation in IrModuleModule._extract_resource_attachment_translations(module, self._lang):
                self._push_translation(*translation)
