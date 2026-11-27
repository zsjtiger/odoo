"""The lazy translations: the translation of the terms when they are used, and the translation aliases."""

from __future__ import annotations

import functools
import logging
from collections.abc import Iterable
from markupsafe import escape, Markup
from odoo.tools.text.i18n import format_list

from .frames import _get_translation_source, get_translated_module

_logger = logging.getLogger('odoo.tools.text.translate')


def get_translation(module: str, lang: str, source: str, args: tuple | dict) -> str:
    """Translate and format using a module, language, source text and args."""
    # get the translation by using the language
    assert lang, "missing language for translation"
    if lang == 'en_US':
        translation = source
    else:
        assert module, "missing module name for translation"
        # imported here: the module of the code translations depends on this one
        from odoo.tools.text.translate.code import code_translations  # noqa: PLC0415
        translation = code_translations.get_python_translations(module, lang).get(source, source)
    # skip formatting if we have no args
    if not args:
        return translation
    # we need to check the args for markup values and for lazy translations
    args_is_dict = isinstance(args, dict)
    if any(isinstance(a, Markup) for a in (args.values() if args_is_dict else args)):
        translation = escape(translation)
    if any(isinstance(a, LazyGettext) for a in (args.values() if args_is_dict else args)):
        if args_is_dict:
            args = {k: v._translate(lang) if isinstance(v, LazyGettext) else v for k, v in args.items()}
        else:
            args = tuple(v._translate(lang) if isinstance(v, LazyGettext) else v for v in args)
    if any(isinstance(a, Iterable) and not isinstance(a, (str, bytes)) for a in (args.values() if args_is_dict else args)):
        # automatically format list-like arguments in a localized way
        def process_translation_arg(v):
            return format_list(env=None, lst=v, lang_code=lang) if isinstance(v, Iterable) and not isinstance(v, (str, bytes)) else v
        if args_is_dict:
            args = {k: process_translation_arg(v) for k, v in args.items()}
        else:
            args = tuple(process_translation_arg(v) for v in args)
    # format
    try:
        return translation % args
    except (TypeError, ValueError, KeyError):
        bad = translation
        # fallback: apply to source before logging exception (in case source fails)
        translation = source % args
        _logger.exception('Bad translation %r for string %r', bad, source)
    return translation


def get_text_alias(source: str, /, *args, **kwargs):
    assert not (args and kwargs)
    assert isinstance(source, str)
    module, lang = _get_translation_source(1)
    return get_translation(module, lang, source, args or kwargs)


@functools.total_ordering
class LazyGettext:
    """ Lazy code translated term.

    Similar to get_text_alias but the translation lookup will be done only at
    __str__ execution.
    This eases the search for terms to translate as lazy evaluated strings
    are declared early.

    A code using translated global variables such as:

    ```
    _lt = LazyTranslate(__name__)
    LABEL = _lt("User")

    def _compute_label(self):
        env = self.with_env(lang=self.partner_id.lang).env
        self.user_label = env._(LABEL)
    ```

    works as expected (unlike the classic get_text_alias implementation).
    """

    __slots__ = ('_args', '_default_lang', '_module', '_source')

    def __init__(self, source, /, *args, _module='', _default_lang='', **kwargs):
        assert not (args and kwargs)
        assert isinstance(source, str)
        self._source = source
        self._args = args or kwargs
        self._module = get_translated_module(_module or 2)
        self._default_lang = _default_lang

    def _translate(self, lang: str = '') -> str:
        module, lang = _get_translation_source(2, self._module, lang, default_lang=self._default_lang)
        return get_translation(module, lang, self._source, self._args)

    def __repr__(self):
        """ Show for the debugger"""
        args = {'_module': self._module, '_default_lang': self._default_lang, '_args': self._args}
        return f"_lt({self._source!r}, **{args!r})"

    def __str__(self):
        """ Translate."""
        return self._translate()

    def __eq__(self, other):
        if not isinstance(other, LazyGettext):
            return False
        return (self._source == other._source and self._args == other._args and
                self._module == other._module and self._default_lang == other._default_lang)

    def __hash__(self):
        raise NotImplementedError()

    def __lt__(self, other):
        raise NotImplementedError()

    def __add__(self, other):
        if isinstance(other, str):
            return self._translate() + other
        elif isinstance(other, LazyGettext):
            return self._translate() + other._translate()
        return NotImplemented

    def __radd__(self, other):
        if isinstance(other, str):
            return other + self._translate()
        return NotImplemented


class LazyTranslate:
    """ Lazy translation template.

    Usage:
    ```
    _lt = LazyTranslate(__name__)
    MYSTR = _lt('Translate X')
    ```

    You may specify a `default_lang` to fallback to a given language on error
    """
    module: str
    default_lang: str

    def __init__(self, module: str, *, default_lang: str = '') -> None:
        self.module = module = get_translated_module(module or 2)
        # set the default lang to en_US for lazy translations in the base module
        self.default_lang = default_lang or ('en_US' if module == 'base' else '')

    def __call__(self, source: str, *args, **kwargs) -> LazyGettext:
        return LazyGettext(source, *args, **kwargs, _module=self.module, _default_lang=self.default_lang)


_ = get_text_alias


_lt = LazyGettext
