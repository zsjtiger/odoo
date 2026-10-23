# Part of Odoo. See LICENSE file for full copyright and licensing details.

from collections.abc import Mapping
from typing import Any

class LangData(Mapping):
    """ A ``dict``-like class which can access field value like a ``res.lang`` record.
    Note: This data class cannot store data for fields with the same name as
    ``dict`` methods, like ``dict.keys``.
    """
    __slots__ = ('__data',)

    def __init__(self, data):
        self.__data = dict(data)

    def __getitem__(self, key):
        return self.__data[key]

    def __len__(self):
        return len(self.__data)

    def __iter__(self):
        return iter(self.__data)

    def __contains__(self, key):
        return key in self.__data

    def __bool__(self) -> bool:
        return bool(self.id)

    def __getattr__(self, name: str) -> Any:
        try:
            return self[name]
        except KeyError:
            raise AttributeError


class LangDataDict(Mapping):
    """ A ``dict`` of :class:`LangData` objects indexed by some key, which returns
    a special dummy :class:`LangData` for missing keys.
    """
    __slots__ = ('__data',)

    def __init__(self, data):
        self.__data = dict(data)

    def __getitem__(self, key: Any) -> LangData:
        try:
            return self.__data[key]
        except KeyError:
            some_lang = next(iter(self.values()))  # should have at least one active language
            return LangData(dict.fromkeys(some_lang, False))

    def __len__(self):
        return len(self.__data)

    def __iter__(self):
        return iter(self.__data)

    def __contains__(self, key):
        return key in self.__data
