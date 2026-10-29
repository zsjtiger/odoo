"""Query strings of the URLs: their encoding and their decoding."""

from __future__ import annotations

import typing as t
from werkzeug.datastructures import iter_multi_items

from .helpers import _make_encode_wrapper, _to_str
from .quote import _fast_url_quote_plus, url_unquote, url_unquote_plus

def _url_encode_impl(
    obj: t.Mapping[str, str] | t.Iterable[tuple[str, str]],
    charset: str,
    sort: bool,
    key: t.Callable[[tuple[str, str]], t.Any] | None,
) -> t.Iterator[str]:
    iterable: t.Iterable[tuple[str, str]] = iter_multi_items(obj)

    if sort:
        iterable = sorted(iterable, key=key)

    for key_str, value_str in iterable:
        if value_str is None:
            continue

        if not isinstance(key_str, bytes):
            key_bytes = str(key_str).encode(charset)
        else:
            key_bytes = key_str

        if not isinstance(value_str, bytes):
            value_bytes = str(value_str).encode(charset)
        else:
            value_bytes = value_str

        yield f"{_fast_url_quote_plus(key_bytes)}={_fast_url_quote_plus(value_bytes)}"

if t.TYPE_CHECKING:
    from werkzeug import datastructures as ds


def _url_unquote_legacy(value: str, unsafe: str = "") -> str:
    try:
        return url_unquote(value, charset="utf-8", errors="strict", unsafe=unsafe)
    except UnicodeError:
        return url_unquote(value, charset="latin1", unsafe=unsafe)


def url_decode(
    s: t.AnyStr,
    charset: str = "utf-8",
    include_empty: bool = True,
    errors: str = "replace",
    separator: str = "&",
    cls: type[ds.MultiDict] | None = None,
) -> ds.MultiDict[str, str]:
    """Parse a query string and return it as a :class:`MultiDict`.

    :param s: The query string to parse.
    :param charset: Decode bytes to string with this charset. If not
        given, bytes are returned as-is.
    :param include_empty: Include keys with empty values in the dict.
    :param errors: Error handling behavior when decoding bytes.
    :param separator: Separator character between pairs.
    :param cls: Container to hold result instead of :class:`MultiDict`.

    .. deprecated:: 2.3
        Will be removed in Werkzeug 2.4. Use ``urllib.parse.parse_qs`` instead.

    .. versionchanged:: 2.1
        The ``decode_keys`` parameter was removed.

    .. versionchanged:: 0.5
        In previous versions ";" and "&" could be used for url decoding.
        Now only "&" is supported. If you want to use ";", a different
        ``separator`` can be provided.

    .. versionchanged:: 0.5
        The ``cls`` parameter was added.
    """
    if cls is None:
        from werkzeug.datastructures import MultiDict  # noqa: F811

        cls = MultiDict
    if isinstance(s, str) and not isinstance(separator, str):
        separator = separator.decode(charset or "ascii")
    elif isinstance(s, bytes) and not isinstance(separator, bytes):
        separator = separator.encode(charset or "ascii")  # type: ignore
    return cls(
        _url_decode_impl(
            s.split(separator), charset, include_empty, errors  # type: ignore
        )
    )


def _url_decode_impl(
    pair_iter: t.Iterable[t.AnyStr], charset: str, include_empty: bool, errors: str
) -> t.Iterator[tuple[str, str]]:
    for pair in pair_iter:
        if not pair:
            continue
        s = _make_encode_wrapper(pair)
        equal = s("=")
        if equal in pair:
            key, value = pair.split(equal, 1)
        else:
            if not include_empty:
                continue
            key = pair
            value = s("")
        yield (
            url_unquote_plus(key, charset, errors),
            url_unquote_plus(value, charset, errors),
        )


def url_encode(
    obj: t.Mapping[str, str] | t.Iterable[tuple[str, str]],
    charset: str = "utf-8",
    sort: bool = False,
    key: t.Callable[[tuple[str, str]], t.Any] | None = None,
    separator: str = "&",
) -> str:
    """URL encode a dict/`MultiDict`.  If a value is `None` it will not appear
    in the result string.  Per default only values are encoded into the target
    charset strings.

    :param obj: the object to encode into a query string.
    :param charset: the charset of the query string.
    :param sort: set to `True` if you want parameters to be sorted by `key`.
    :param separator: the separator to be used for the pairs.
    :param key: an optional function to be used for sorting.  For more details
                check out the :func:`sorted` documentation.

    .. deprecated:: 2.3
        Will be removed in Werkzeug 2.4. Use ``urllib.parse.urlencode`` instead.

    .. versionchanged:: 2.1
        The ``encode_keys`` parameter was removed.

    .. versionchanged:: 0.5
        Added the ``sort``, ``key``, and ``separator`` parameters.
    """
    separator = _to_str(separator, "ascii")
    return separator.join(_url_encode_impl(obj, charset, sort, key))
