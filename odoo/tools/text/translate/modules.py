"""Translations of the modules: their readers, their import and their loading into the database."""

from __future__ import annotations

import fnmatch
import locale
import logging
import os
import polib
import re
import typing
from collections import defaultdict, namedtuple
from collections.abc import Iterable, Iterator
from contextlib import suppress
from os.path import join
from babel.messages import extract
from psycopg2.extras import Json
from odoo.tools.config import config
from odoo.tools.misc import file_open, file_path, frozendict, split_every
from odoo.tools.sql import SQL
from odoo.tools.constants import IN_MAX

if typing.TYPE_CHECKING:

    pass

from .base import JAVASCRIPT_TRANSLATION_COMMENT, PYTHON_TRANSLATION_COMMENT, ParsedTranslation, StoredTranslations, get_iso_codes
from .extract import is_meaningful_term
from .files import TranslationFileWriter, translation_file_reader

_logger = logging.getLogger('odoo.tools.text.translate')


def trans_export(lang, modules, buffer, format, env):
    reader = TranslationModuleReader(env.cr, modules=modules, lang=lang)
    if not reader:
        return False
    writer = TranslationFileWriter(buffer, fileformat=format, lang=lang)
    writer.write_rows(reader)
    return True


def trans_export_records(lang, model_name, ids, buffer, format, env):
    reader = TranslationRecordReader(env.cr, model_name, ids, lang=lang)
    if not reader:
        return False
    writer = TranslationFileWriter(buffer, fileformat=format, lang=lang)
    writer.write_rows(reader)
    return True


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


def DeepDefaultDict():
    return defaultdict(DeepDefaultDict)


class TranslationImporter:
    """ Helper object for importing translation files to a database.
    This class provides a convenient API to load the translations from many
    files and import them all at once, which helps speeding up the whole import.
    """

    def __init__(self, cr, verbose=True):
        self.cr = cr
        self.verbose = verbose
        from odoo import api  # noqa: PLC0415
        self.env = api.Environment(cr, api.SUPERUSER_ID, {})

        # {model_name: {field_name: {xmlid: {lang: value}}}}
        self.model_translations = DeepDefaultDict()
        # {model_name: {field_name: {xmlid: {src: {lang: value}}}}}
        self.model_terms_translations = DeepDefaultDict()
        self.imported_langs = set()

    def load_file(self, filepath, lang, xmlids=None, module=None):
        """ Load translations from the given file path.

        :param filepath: file path to open
        :param lang: language code of the translations contained in the file;
                     the language must be present and activated in the database
        :param xmlids: if given, only translations for records with xmlid in xmlids will be loaded
        :param module: if given, the file will be interpreted as a data file containing translations
        """
        with suppress(FileNotFoundError), file_open(filepath, mode='rb', env=self.env) as fileobj:
            if self.verbose:
                _logger.info('loading base translation file %s for language %s', filepath, lang)
            fileformat = os.path.splitext(filepath)[-1][1:].lower()
            self.load(fileobj, fileformat, lang, xmlids=xmlids, module=module)

    def load(self, fileobj, fileformat, lang, xmlids=None, module=None):
        """Load translations from the given file object.

        :param fileobj: buffer open to a translation file
        :param fileformat: format of the `fielobj` file, one of 'po', 'csv', or 'xml'
        :param lang: language code of the translations contained in `fileobj`;
                     the language must be present and activated in the database
        :param xmlids: if given, only translations for records with xmlid in xmlids will be loaded
        :param module: if given, the file will be interpreted as a data file containing translations
        """
        if self.verbose:
            _logger.info('loading translation file for language %s', lang)
        if not self.env['res.lang']._lang_get(lang):
            _logger.error("Couldn't read translation for lang '%s', language not found", lang)
            return None
        try:
            fileobj.seek(0)
            reader = translation_file_reader(fileobj, fileformat=fileformat, module=module)
            self._load(reader, lang, xmlids)
        except IOError:
            iso_lang = get_iso_codes(lang)
            filename = '[lang: %s][format: %s]' % (iso_lang or 'new', fileformat)
            _logger.exception("couldn't read translation file %s", filename)

    def _load(self, reader, lang, xmlids=None):
        if xmlids and not isinstance(xmlids, set):
            xmlids = set(xmlids)
        valid_langs = get_base_langs(lang)
        for row in reader:
            if not row.get('value') or not row.get('src'):  # ignore empty translations
                continue
            if row.get('type') == 'code':  # ignore code translations
                continue
            if row.get('lang', lang) not in valid_langs:
                continue
            model_name = row.get('imd_model')
            module_name = row['module']
            if model_name not in self.env:
                continue
            field_name = row['name'].split(',')[1]
            field = self.env[model_name]._fields.get(field_name)
            if not field or not field.translate or not field.store:
                continue
            xmlid = module_name + '.' + row['imd_name']
            if xmlids and xmlid not in xmlids:
                continue
            if row.get('type') == 'model' and field.translate is True:
                self.model_translations[model_name][field_name][xmlid][lang] = row['value']
                self.imported_langs.add(lang)
            elif row.get('type') == 'model_terms' and callable(field.translate):
                self.model_terms_translations[model_name][field_name][xmlid][row['src']][lang] = row['value']
                self.imported_langs.add(lang)

    def save(self, overwrite=False, force_overwrite=False):
        """ Save translations to the database.

        For a record with 'noupdate' in ``ir_model_data``, its existing translations
        will be overwritten if ``force_overwrite or (not noupdate and overwrite)``.

        An existing translation means:
        * model translation: the ``jsonb`` value in database has the language code as key;
        * model terms translation: the term value in the language is different from the term value in ``en_US``.
        """
        if not self.model_translations and not self.model_terms_translations:
            return

        env = self.env
        env.flush_all()

        for model_name, model_dictionary in self.model_terms_translations.items():
            Model = env[model_name]
            model_table = Model._table
            fields = Model._fields
            # field_name, {xmlid: {src: {lang: value}}}
            for field_name, field_dictionary in model_dictionary.items():
                field = fields.get(field_name)
                for sub_xmlids in split_every(IN_MAX, field_dictionary.keys()):
                    # [module_name, imd_name, module_name, imd_name, ...]
                    params = [xmlid.split('.', maxsplit=1) for xmlid in sub_xmlids]
                    rows = env.execute_query(SQL("""
                        SELECT m.id, imd.module || '.' || imd.name, m.%s, imd.noupdate
                        FROM %s m, "ir_model_data" imd
                        WHERE m.id = imd.res_id
                        AND (%s)
                    """, SQL.identifier(field_name), SQL.identifier(model_table), SQL(" OR ").join(
                        SQL("(imd.module = %s AND imd.name = %s)", *param)
                        for param in params
                    )))

                    # [id, translations, id, translations, ...]
                    params = []
                    for id_, xmlid, values, imd_noupdate in rows:
                        if not values:
                            continue
                        _value_en = values.get('_en_US', values['en_US'])
                        if not _value_en:
                            continue

                        # {src: {lang: term_lang}}
                        record_dictionary = field_dictionary[xmlid]
                        # {lang: {src: term_lang}}
                        term_updates = {}
                        for term_en, translations in record_dictionary.items():
                            for lang, value in translations.items():
                                term_updates.setdefault(lang, {})[term_en] = value
                        do_overwrite = force_overwrite or (not imd_noupdate and overwrite)
                        updated_values = dict(StoredTranslations(values).translated(
                            env, field, env.lang or 'en_US', term_updates, overwrite=do_overwrite,
                        ))
                        changed_values = {}
                        for lang in term_updates:
                            new_val = updated_values.get(lang)
                            if values.get(lang) != new_val:
                                changed_values[lang] = new_val
                            if f'_{lang}' in values:
                                changed_values[f'_{lang}'] = None
                        if changed_values:
                            params.append((id_, Json(changed_values)))
                    if params:
                        env.execute_query(SQL("""
                            UPDATE %(table)s AS m
                            SET %(field_name)s = jsonb_strip_nulls(%(field_name)s || t.value)
                            FROM (
                                VALUES %(values)s
                            ) AS t(id, value)
                            WHERE m.id = t.id
                        """, table=SQL.identifier(model_table), field_name=SQL.identifier(field_name), values=SQL(", ").join(
                            SQL("(%s, %s::jsonb)", *param)
                            for param in params
                        )))

        self.model_terms_translations.clear()

        for model_name, model_dictionary in self.model_translations.items():
            Model = env[model_name]
            model_table = Model._table
            for field_name, field_dictionary in model_dictionary.items():
                for sub_field_dictionary in split_every(IN_MAX, field_dictionary.items()):
                    # Parallel arrays + ORDINALITY preserve sub_field_dictionary order
                    # so colliding xmlids merge deterministically in SQL.
                    imd_modules, imd_names, values = [], [], []
                    for xmlid, translations in sub_field_dictionary:
                        module, name = xmlid.split('.', maxsplit=1)
                        imd_modules.append(module)
                        imd_names.append(name)
                        values.append(Json(translations))

                    field = SQL.identifier(field_name)
                    if force_overwrite:
                        value_query = SQL("m.%(field)s || merged.noupdate_value || merged.update_value", field=field)
                    elif overwrite:
                        value_query = SQL("merged.noupdate_value || m.%(field)s || merged.update_value", field=field)
                    else:
                        value_query = SQL("merged.noupdate_value || merged.update_value || m.%(field)s", field=field)

                    # Single UPDATE via CTEs:
                    # 1. input: unnest imported (module, name, translations) with ordinality
                    # 2. entries: resolve xmlid → res_id and expand jsonb keys
                    # 3. merged: aggregate per res_id
                    env.execute_query(SQL("""
                        WITH input(imd_module, imd_name, value, id) AS (
                            SELECT * FROM unnest(%(imd_modules)s::text[], %(imd_names)s::text[], %(values)s::jsonb[]) WITH ORDINALITY
                        ),
                        entries AS (
                            SELECT imd.res_id, imd.noupdate, input.id, translation.key, translation.value
                            FROM input
                            JOIN "ir_model_data" AS imd
                            ON imd.model = %(model_name)s
                            AND imd.module = input.imd_module
                            AND imd.name = input.imd_name
                            CROSS JOIN LATERAL jsonb_each(input.value) AS translation(key, value)
                        ),
                        merged AS (
                            SELECT
                                res_id,
                                COALESCE(
                                    jsonb_object_agg(key, value ORDER BY id ASC) FILTER (WHERE noupdate),
                                    '{}'::jsonb
                                ) AS noupdate_value,
                                COALESCE(
                                    jsonb_object_agg(key, value ORDER BY id ASC) FILTER (WHERE NOT noupdate),
                                    '{}'::jsonb
                                ) AS update_value
                            FROM entries
                            GROUP BY res_id
                        )
                        UPDATE %(table)s AS m
                        SET %(field)s = %(value_query)s
                        FROM merged
                        WHERE m.id = merged.res_id
                    """,
                        imd_modules=imd_modules,
                        imd_names=imd_names,
                        values=values,
                        model_name=model_name,
                        table=SQL.identifier(model_table),
                        field=field,
                        value_query=value_query,
                    ))

        self.model_translations.clear()

        env.invalidate_all()
        env.transaction.invalidate_ormcache()
        if self.verbose:
            _logger.info("translations are loaded successfully")


def get_locales(lang=None):
    if lang is None:
        lang = locale.getlocale()[0]

    def process(enc):
        ln = locale._build_localename((lang, enc))
        yield ln
        nln = locale.normalize(ln)
        if nln != ln:
            yield nln

    for x in process('utf8'): yield x

    prefenc = locale.getpreferredencoding()
    if prefenc:
        for x in process(prefenc): yield x

        prefenc = {
            'latin1': 'latin9',
            'iso-8859-1': 'iso8859-15',
            'cp1252': '1252',
        }.get(prefenc.lower())
        if prefenc:
            for x in process(prefenc): yield x

    yield lang


def resetlocale():
    # locale.resetlocale is bugged with some locales.
    for ln in get_locales():
        try:
            return locale.setlocale(locale.LC_ALL, ln)
        except locale.Error:
            continue


def load_language(cr, lang):
    """ Loads a translation terms for a language.

    Used mainly to automate language loading at db initialization.

    :param cr:
    :param str lang: language ISO code with optional underscore (``_``) and
        l10n flavor (ex: 'fr', 'fr_BE', but not 'fr-BE')
    """
    from odoo import api  # noqa: PLC0415
    env = api.Environment(cr, api.SUPERUSER_ID, {})
    lang_ids = env['res.lang'].with_context(active_test=False).search([('code', '=', lang)]).ids
    installer = env['base.language.install'].create({'lang_ids': [(6, 0, lang_ids)]})
    installer.lang_install()


def get_base_langs(lang: str) -> list[str]:
    base_lang = lang.split('_', 1)[0]
    langs = [base_lang]
    # LAC (~non-peninsular) spanishes have a second base
    if base_lang == 'es' and lang not in ('es_ES', 'es_419'):
        langs.append('es_419')
    # HK Chinese ~ Taiwan Chinese
    if lang == 'zh_HK':
        langs.append('zh_TW')
    if lang != base_lang:
        langs.append(lang)
    return langs


def get_po_paths(module_name: str, lang: str) -> Iterator[str]:
    po_paths = (
        join(module_name, dir_, filename + '.po')
        for filename in get_base_langs(lang)
        for dir_ in ('i18n', 'i18n_extra')
    )
    for path in po_paths:
        with suppress(FileNotFoundError):
            yield file_path(path)


def get_datafile_translation_path(module_name: str) -> Iterator[str]:
    from odoo.modules import Manifest  # noqa: PLC0415
    # if we are importing a module, we have an env, hide warnings
    manifest = Manifest.for_addon(module_name, display_warning=False) or {}
    for data_type in ('data', 'demo'):
        for path in manifest.get(data_type, ()):
            if path.endswith(('.xml', '.csv')):
                yield file_path(join(module_name, path))


CHARSET_REGEX = re.compile(rb'Content-Type:[^\n]+charset=([\w_\-:\.]+)')


def get_translations_for_references(po_path: str, references: Iterable[str]) -> dict[str, dict[str, str]]:
    """A faster extractor of translations for the given references from a PO file.

    The references should be location strings to look for in PO entries (comments starting with ``#:``).

    We use a single-pass approach to read the file in binary mode, locate the relevant entries,
    and parse only these entries in one go with ``polib``.

    Since we parse the file manually, we have two requirements:
    1. The PO file should be well-formed (valid after ``msgcat file.po``).
    2. Each entry must be separated by at least two consecutive newlines.

    :param str po_path: Path to the PO file.
    :param Iterable[str] references: List of reference strings to look for.
    :return: Dictionary mapping references to a dictionary mapping msgid to msgstr.
    """
    normalized_references = {ref.strip() for ref in references if ref and ref.strip()}
    if not normalized_references:
        return {}

    try:
        with file_open(po_path, 'rb') as po_file:
            data = po_file.read()
    except FileNotFoundError:
        return {}

    if not data:
        return {}

    # Normalize line endings to LF for consistent processing.
    data = data.replace(b'\r\n', b'\n')

    data_find = data.find
    data_rfind = data.rfind
    data_len = len(data)

    double_newline = b'\n\n'
    double_newline_len = 2

    # Find the header entry and extract the encoding if present.
    #
    #                        [top of file comments]
    # (header_start_pos) --> msgid ""[\n]
    #                        msgstr ""[\n]
    #                        "Content-Type: text/plain; charset=UTF-8\n"[\n]
    #                        "X-key: value"[\n] <-- (header_end_pos)
    #                        [\n]
    #                        [first entry][\n]

    header_start_pos = data_find(b'msgid ""\nmsgstr ""')
    if header_start_pos == -1:
        return {}

    header_end_pos = data_find(double_newline, header_start_pos)
    if header_end_pos == -1:
        return {}

    header_bytes = data[0: header_end_pos]
    match = CHARSET_REGEX.search(header_bytes)
    encoding = match.group(1).decode('ascii') if match else 'utf-8'

    # Store the entries to concatenate later. The first entry is the header.
    entries = [header_bytes]

    encoded_references = {ref.encode(encoding, errors='ignore') for ref in normalized_references}
    matched_entry_positions = set()
    nl_hash_colon = b'\n#:'
    nl_hash_colon_len = 3
    search_start_pos = header_end_pos

    while True:
        search_start_pos = data_find(nl_hash_colon, search_start_pos)
        if search_start_pos == -1:
            break

        line_end_pos = data_find(b'\n', search_start_pos + nl_hash_colon_len)
        if line_end_pos == -1:
            line_end_pos = data_len

        line_bytes = data[search_start_pos + nl_hash_colon_len: line_end_pos]
        refs_on_line = set(line_bytes.split())

        if not encoded_references.isdisjoint(refs_on_line):
            # We found a line with at least one reference we need. Find the entry boundaries:
            #
            #                       [previous entry][\n]
            #                       [\n]
            # (entry_start_pos) --> #. base[\n] <-- (full_reference_start)
            #                       #: reference1 reference2[\n]
            #                       msgid "source"[\n]
            #                       msgstr ""[\n]
            #                       "line1\n"[\n]
            #                       "line2\n"[\n] <-- (entry_end_pos)
            #                       [\n]
            #                       [next entry]

            entry_start_pos = data_rfind(double_newline, header_end_pos, search_start_pos)
            if entry_start_pos == -1:
                entry_start_pos = header_end_pos
            else:
                entry_start_pos += double_newline_len

            if entry_start_pos not in matched_entry_positions:
                # This entry has not been added to `entries` yet, so we add it now.
                matched_entry_positions.add(entry_start_pos)

                entry_end_pos = data_find(double_newline, search_start_pos)
                if entry_end_pos == -1:
                    entry_end_pos = data_len

                entries.append(data[entry_start_pos:entry_end_pos])

                search_start_pos = entry_end_pos
                continue

        search_start_pos = line_end_pos

    if len(entries) == 1:
        return {}

    # Parse all entries in a single polib call.
    filtered_po = polib.pofile(double_newline.join(entries).decode(encoding), encoding=encoding)

    translations = defaultdict(dict)

    for entry in filtered_po:
        for occ in entry.occurrences:
            occ_str = f'{occ[0]}:{occ[1]}' if occ[1] else occ[0]
            if occ_str in normalized_references and entry.msgstr and entry.msgid:
                translations[occ_str][entry.msgid] = entry.msgstr

    return dict(translations)


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


def _get_translation_upgrade_queries(cr, field):
    """ Return a pair of lists ``migrate_queries, cleanup_queries`` of SQL queries. The queries in
    ``migrate_queries`` do migrate the data from table ``_ir_translation`` to the corresponding
    field's column, while the queries in ``cleanup_queries`` remove the corresponding data from
    table ``_ir_translation``.
    """
    from odoo.modules.registry import Registry  # noqa: PLC0415
    Model = Registry(cr.dbname)[field.model_name]
    translation_name = f"{field.model_name},{field.name}"
    migrate_queries = []
    cleanup_queries = []

    if field.translate is True:
        emtpy_src = """'{"en_US": ""}'::jsonb"""
        query = f"""
            WITH t AS (
                SELECT it.res_id as res_id, jsonb_object_agg(it.lang, it.value) AS value, bool_or(imd.noupdate) AS noupdate
                  FROM _ir_translation it
             LEFT JOIN ir_model_data imd
                    ON imd.model = %s AND imd.res_id = it.res_id AND imd.module != '__export__'
                 WHERE it.type = 'model' AND it.name = %s AND it.state = 'translated'
              GROUP BY it.res_id
            )
            UPDATE {Model._table} m
               SET "{field.name}" = CASE WHEN m."{field.name}" IS NULL THEN {emtpy_src} || t.value
                                         WHEN t.noupdate IS FALSE THEN t.value || m."{field.name}"
                                         ELSE m."{field.name}" || t.value
                                     END
              FROM t
             WHERE t.res_id = m.id
        """
        migrate_queries.append(cr.mogrify(query, [Model._name, translation_name]).decode())

        query = "DELETE FROM _ir_translation WHERE type = 'model' AND state = 'translated' AND name = %s"
        cleanup_queries.append(cr.mogrify(query, [translation_name]).decode())

    # upgrade model_terms translation: one update per field per record
    if callable(field.translate):
        cr.execute("SELECT code FROM res_lang WHERE active IS TRUE")
        languages = {l[0] for l in cr.fetchall()}
        field_name_sql = SQL.identifier('m', field.name)
        table_sql = SQL.identifier(Model._table)
        query = SQL("""
            SELECT t.res_id, %s, t.value, t.noupdate
              FROM t
              JOIN %s m ON t.res_id = m.id
        """, field_name_sql, table_sql)
        if translation_name == 'ir.ui.view,arch_db':
            cr.execute("SELECT id from ir_module_module WHERE name = 'website' AND state='installed'")
            if cr.fetchone():
                query = SQL("""
                    SELECT t.res_id, %(field_name)s, t.value, t.noupdate, l.code
                      FROM t
                      JOIN %(table)s m ON t.res_id = m.id
                      JOIN website w ON m.website_id = w.id
                      JOIN res_lang l ON w.default_lang_id = l.id
                    UNION
                    SELECT t.res_id, %(field_name)s, t.value, t.noupdate, 'en_US'
                      FROM t
                      JOIN %(table)s m ON t.res_id = m.id
                     WHERE m.website_id IS NULL
                """, field_name=field_name_sql, table=table_sql)
        cr.execute(SQL("""
            WITH t0 AS (
                -- aggregate translations by source term --
                SELECT res_id, lang, jsonb_object_agg(src, value) AS value
                  FROM _ir_translation
                 WHERE type = 'model_terms' AND name = %s AND state = 'translated'
              GROUP BY res_id, lang
            ),
            t AS (
                -- aggregate translations by lang --
                SELECT t0.res_id AS res_id, jsonb_object_agg(t0.lang, t0.value) AS value, bool_or(imd.noupdate) AS noupdate
                  FROM t0
             LEFT JOIN ir_model_data imd
                    ON imd.model = %s AND imd.res_id = t0.res_id
              GROUP BY t0.res_id
            ) %s""", translation_name, Model._name, query))
        for id_, new_translations, translations, noupdate, *extra in cr.fetchall():
            if not new_translations:
                continue
            # new_translations contains translations updated from the latest po files
            src_value = new_translations.pop('en_US')
            src_terms = ParsedTranslation(field, src_value).terms
            for lang, dst_value in new_translations.items():
                terms_mapping = translations.setdefault(lang, {})
                dst_terms = ParsedTranslation(field, dst_value).terms
                for src_term, dst_term in zip(src_terms, dst_terms):
                    if src_term == dst_term or noupdate:
                        terms_mapping.setdefault(src_term, dst_term)
                    else:
                        terms_mapping[src_term] = dst_term
            new_values = {
                lang: field.translate(terms_mapping.get, src_value)
                for lang, terms_mapping in translations.items()
            }
            if "en_US" not in new_values:
                new_values["en_US"] = field.translate(lambda v: None, src_value)
            if extra and extra[0] not in new_values:
                new_values[extra[0]] = field.translate(lambda v: None, src_value)
            elif not extra:
                missing_languages = languages - set(translations)
                if missing_languages:
                    src_value = field.translate(lambda v: None, src_value)
                    for lang in sorted(missing_languages):
                        new_values[lang] = src_value
            query = f'UPDATE "{Model._table}" SET "{field.name}" = %s WHERE id = %s'
            migrate_queries.append(cr.mogrify(query, [Json(new_values), id_]).decode())

        query = "DELETE FROM _ir_translation WHERE type = 'model_terms' AND state = 'translated' AND name = %s"
        cleanup_queries.append(cr.mogrify(query, [translation_name]).decode())

    return migrate_queries, cleanup_queries
