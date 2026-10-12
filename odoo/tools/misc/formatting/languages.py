"""The languages of the formatting: the language data of a code, and the babel locales."""

from __future__ import annotations

import typing
from functools import lru_cache
import babel

if typing.TYPE_CHECKING:
    from odoo.api import Environment
    from odoo.addons.base.models.res_lang import LangData


def get_lang(env: Environment, lang_code: str | None = None) -> LangData:
    """
    Retrieve the first lang object installed, by checking the parameter lang_code,
    the context and then the company. If no lang is installed from those variables,
    fallback on english or on the first lang installed in the system.

    :param env:
    :param str lang_code: the locale (i.e. en_US)
    :return LangData: the first lang found that is installed on the system.
    """
    langs = [code for code, _ in env['res.lang'].get_installed()]
    lang = 'en_US' if 'en_US' in langs else langs[0]
    if lang_code and lang_code in langs:
        lang = lang_code
    elif (context_lang := env.context.get('lang')) in langs:
        lang = context_lang
    elif (company_lang := env.user.with_context(lang='en_US').company_id.partner_id.lang) in langs:
        lang = company_lang
    return env['res.lang']._get_data(code=lang)


@lru_cache
def babel_locale_parse(lang_code: str | None) -> babel.Locale:
    if lang_code:
        try:
            return babel.Locale.parse(lang_code)
        except Exception:  # noqa: BLE001
            pass
    try:
        return babel.Locale.default()
    except Exception:  # noqa: BLE001
        return babel.Locale.parse("en_US")
