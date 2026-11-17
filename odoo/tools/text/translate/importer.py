"""Import of the translations of the modules and of the records into the database."""

from __future__ import annotations

import logging
import os
from collections import defaultdict
from contextlib import suppress
from psycopg2.extras import Json
from odoo.tools.misc import file_open, split_every
from odoo.tools.sql import SQL
from odoo.tools.constants import IN_MAX
from .base import get_iso_codes
from .stored import ParsedTranslation, StoredTranslations
from .files import translation_file_reader

from .languages import get_base_langs

_logger = logging.getLogger('odoo.tools.text.translate')


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
