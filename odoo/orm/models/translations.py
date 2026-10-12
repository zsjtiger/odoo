# Part of Odoo. See LICENSE file for full copyright and licensing details.
"""Field translations: reading and updating the translations of the fields."""

from __future__ import annotations

import logging
import re
import typing

import psycopg2.errors
import psycopg2.extensions

from odoo.exceptions import MissingError
from odoo.tools.translate import LazyTranslate


from odoo.orm.fields.textual import StoredTranslations


if typing.TYPE_CHECKING:
    from collections.abc import Collection, Sequence
    from odoo.orm.core.types import ValuesType


_lt = LazyTranslate('base')
_logger = logging.getLogger('odoo.models')
_unlink = logging.getLogger('odoo.models.unlink')

regex_order = re.compile(r'''
    ^
    (\s*
        (?P<term>((?P<field>[a-z0-9_]+)(\.(?P<property>[a-z0-9_]+))?(:(?P<func>[a-z_]+))?))
        (\s+(?P<direction>desc|asc))?
        (\s+(?P<nulls>nulls\ first|nulls\ last))?
        \s*
        (,|$)
    )+
    (?<!,)
    $
''', re.IGNORECASE | re.VERBOSE)
regex_order_part_read_group = re.compile(r"""
    \s*
    (?P<term>(?P<field>[a-z0-9_]+)(\.([\w\.]+))?(:(?P<func>[a-z_]+))?)
    (\s+(?P<direction>desc|asc))?
    (\s+(?P<nulls>nulls\ first|nulls\ last))?
    \s*
""", re.IGNORECASE | re.VERBOSE)
regex_field_agg = re.compile(r'(\w+)(?::(\w+)(?:\((\w+)\))?)?')  # For read_group
regex_read_group_spec = re.compile(r'(\w+)(\.([\w\.]+))?(?::(\w+))?$')  # For _read_group

INSERT_BATCH_SIZE = 100
UPDATE_BATCH_SIZE = 100
SQL_DEFAULT = psycopg2.extensions.AsIs("DEFAULT")



def get_field_translations(self, field_name: str, langs: Collection[str] | None=None) -> tuple[list[dict[str, str]], dict[str, typing.Any]]:
    self.ensure_one()
    field = self._fields[field_name]
    # We don't forbid reading inactive/non-existing languages,
    langs = set(langs or [l[0] for l in self.env['res.lang'].get_installed()])
    self_lang = self.with_context(check_translations=True, prefetch_langs=True)
    val_en = self_lang.with_context(lang='en_US')[field_name]
    if not field.translate:
        translations = []
    elif field.translate is True:
        translations = [{
            'lang': lang,
            'source': val_en,
            'value': self_lang.with_context(lang=lang)[field_name]
        } for lang in langs]
    else:
        translation_dictionary = StoredTranslations._get_translation_dictionary(
            field, val_en, {lang: self_lang.with_context(lang=lang)[field_name] for lang in langs}
        )
        translations = [{
            'lang': lang,
            'source': term_en,
            'value': term_lang if term_lang != term_en else ''
        } for term_en, translations in translation_dictionary.items()
            for lang, term_lang in translations.items()]
    context = {}
    context['translation_type'] = 'text' if field.type in ['text', 'html'] else 'char'
    context['translation_show_source'] = callable(field.translate)

    return translations, context


def _get_base_lang(self) -> str:
    self.ensure_one()
    return 'en_US'


def _read_format(self, fnames: Sequence[str], load: str='_classic_read') -> list[ValuesType]:
    data = [(record, {'id': record.id}) for record in self]
    use_display_name = (load == '_classic_read')
    for name in fnames:
        field = self._fields[name]
        if field.type == 'properties':
            values_list = []
            records = []
            for record, vals in data:
                try:
                    values_list.append(record[name])
                    records.append(record.id)
                except MissingError:
                    vals.clear()

            results = field.convert_to_read_multi(values_list, self.browse(records))
            for record_read_vals, convert_result in zip(data, results):
                record_read_vals[1][name] = convert_result
            continue

        convert = field.convert_to_read
        if field.type == 'binary' and load == 'web':
            def binary_convert(value, record, use_display_name):
                if not value:
                    return False
                res = {}
                # Include the file name
                filename = value.filename
                if filename and filename != field.name:
                    res['filename'] = filename
                # For NewIds, always include the content
                include_content = not any(record._ids)
                if include_content:
                    res['content'] = value.to_base64()
                res['size'] = value.size
                res['checksum'] = value.checksum
                return res
            convert = binary_convert

        for record, vals in data:
            # missing records have their vals empty
            if not vals:
                continue
            try:
                vals[name] = convert(record[name], record, use_display_name)
            except MissingError:
                vals.clear()
    result = [vals for record, vals in data if vals]

    return result


def update_field_translations(self, field_name: str, translations: dict[str, str | typing.Literal[False] | dict[str, str]], source_lang: str='') -> bool:
    return self._update_field_translations(field_name, translations, source_lang=source_lang)
