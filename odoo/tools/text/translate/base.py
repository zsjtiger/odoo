"""The translation helpers shared by the lazy and the stored translations: the languages, the text terms, the quoting and the XML ids."""

from __future__ import annotations

import re
from lxml import html


PYTHON_TRANSLATION_COMMENT = 'odoo-python'


JAVASCRIPT_TRANSLATION_COMMENT = 'odoo-javascript'


def get_iso_codes(lang: str) -> str:
    if lang.find('_') != -1:
        lang_items = lang.split('_')
        if lang_items[0] == lang_items[1].lower():
            lang = lang_items[0]
    return lang


def get_text_content(term):
    """ Return the textual content of the given term. """
    content = html.fromstring(term).text_content()
    return " ".join(content.split())


def is_text(term):
    """ Return whether the term has only text. """
    it = html.fromstring(f"<root>{term}</root>").iter()
    next(it)  # consume <root>
    return next(it, None) is None


def quote(s):
    """Returns quoted PO term string, with special PO characters escaped"""
    assert r"\n" not in s, "Translation terms may not include escaped newlines ('\\n'), please use only literal newlines! (in '%s')" % s
    return '"%s"' % s.replace('\\','\\\\') \
                     .replace('"','\\"') \
                     .replace('\n', '\\n"\n"')


re_escaped_char = re.compile(r"(\\.)")


re_escaped_replacements = {'n': '\n', 't': '\t',}


def _sub_replacement(match_obj):
    return re_escaped_replacements.get(match_obj.group(1)[1], match_obj.group(1)[1])


def unquote(str):
    """Returns unquoted PO term string, with special PO characters unescaped"""
    return re_escaped_char.sub(_sub_replacement, str[1:-1])


def parse_xmlid(xmlid: str, default_module: str) -> tuple[str, str]:
    split_id = xmlid.split('.', maxsplit=1)
    if len(split_id) == 1:
        return default_module, split_id[0]
    return split_id[0], split_id[1]
