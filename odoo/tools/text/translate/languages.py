"""The languages of the translations: their locales, their base languages and their loading."""

from __future__ import annotations

import locale


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
