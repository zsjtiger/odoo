"""Quoting and unquoting of the URLs."""

from __future__ import annotations

import typing as t

from .charsets import _always_safe, _bytetohex, _hextobyte

_unquote_maps: dict[frozenset[int], dict[bytes, int]] = {frozenset(): _hextobyte}


def _unquote_to_bytes(string: str | bytes, unsafe: str | bytes = "") -> bytes:
    if isinstance(string, str):
        string = string.encode("utf-8")

    if isinstance(unsafe, str):
        unsafe = unsafe.encode("utf-8")

    unsafe = frozenset(bytearray(unsafe))
    groups = iter(string.split(b"%"))
    result = bytearray(next(groups, b""))

    try:
        hex_to_byte = _unquote_maps[unsafe]
    except KeyError:
        hex_to_byte = _unquote_maps[unsafe] = {
            h: b for h, b in _hextobyte.items() if b not in unsafe
        }

    for group in groups:
        code = group[:2]

        if code in hex_to_byte:
            result.append(hex_to_byte[code])
            result.extend(group[2:])
        else:
            result.append(37)  # %
            result.extend(group)

    return bytes(result)


def _make_fast_url_quote(
    charset: str = "utf-8",
    errors: str = "strict",
    safe: str | bytes = "/:",
    unsafe: str | bytes = "",
) -> t.Callable[[bytes], str]:
    """Precompile the translation table for a URL encoding function.

    Unlike :func:`url_quote`, the generated function only takes the
    string to quote.

    :param charset: The charset to encode the result with.
    :param errors: How to handle encoding errors.
    :param safe: An optional sequence of safe characters to never encode.
    :param unsafe: An optional sequence of unsafe characters to always encode.
    """
    if isinstance(safe, str):
        safe = safe.encode(charset, errors)

    if isinstance(unsafe, str):
        unsafe = unsafe.encode(charset, errors)

    safe = (frozenset(bytearray(safe)) | _always_safe) - frozenset(bytearray(unsafe))
    table = [chr(c) if c in safe else f"%{c:02X}" for c in range(256)]

    def quote(string: bytes) -> str:
        return "".join([table[c] for c in string])

    return quote


_fast_quote_plus = _make_fast_url_quote(safe=" ", unsafe="+")


def _fast_url_quote_plus(string: bytes) -> str:
    return _fast_quote_plus(string).replace(" ", "+")


def url_quote(
    string: str | bytes,
    charset: str = "utf-8",
    errors: str = "strict",
    safe: str | bytes = "/:",
    unsafe: str | bytes = "",
) -> str:
    """URL encode a single string with a given encoding.

    :param s: the string to quote.
    :param charset: the charset to be used.
    :param safe: an optional sequence of safe characters.
    :param unsafe: an optional sequence of unsafe characters.

    .. deprecated:: 2.3
        Will be removed in Werkzeug 2.4. Use ``urllib.parse.quote`` instead.

    .. versionadded:: 0.9.2
       The `unsafe` parameter was added.
    """

    if not isinstance(string, (str, bytes, bytearray)):
        string = str(string)
    if isinstance(string, str):
        string = string.encode(charset, errors)
    if isinstance(safe, str):
        safe = safe.encode(charset, errors)
    if isinstance(unsafe, str):
        unsafe = unsafe.encode(charset, errors)
    safe = (frozenset(bytearray(safe)) | _always_safe) - frozenset(bytearray(unsafe))
    rv = bytearray()
    for char in bytearray(string):
        if char in safe:
            rv.append(char)
        else:
            rv.extend(_bytetohex[char])
    return bytes(rv).decode(charset)


def url_quote_plus(
    string: str, charset: str = "utf-8", errors: str = "strict", safe: str = ""
) -> str:
    """URL encode a single string with the given encoding and convert
    whitespace to "+".

    :param s: The string to quote.
    :param charset: The charset to be used.
    :param safe: An optional sequence of safe characters.

    .. deprecated:: 2.3
        Will be removed in Werkzeug 2.4. Use ``urllib.parse.quote_plus`` instead.
    """

    return url_quote(string, charset, errors, safe + " ", "+").replace(" ", "+")


def url_unquote(
    s: str | bytes,
    charset: str = "utf-8",
    errors: str = "replace",
    unsafe: str = "",
) -> str:
    """URL decode a single string with a given encoding.  If the charset
    is set to `None` no decoding is performed and raw bytes are
    returned.

    :param s: the string to unquote.
    :param charset: the charset of the query string.  If set to `None`
        no decoding will take place.
    :param errors: the error handling for the charset decoding.

    .. deprecated:: 2.3
        Will be removed in Werkzeug 2.4. Use ``urllib.parse.unquote`` instead.
    """
    rv = _unquote_to_bytes(s, unsafe)
    if charset is None:
        return rv
    return rv.decode(charset, errors)


def url_unquote_plus(
    s: str | bytes, charset: str = "utf-8", errors: str = "replace"
) -> str:
    """URL decode a single string with the given `charset` and decode "+" to
    whitespace.

    Per default encoding errors are ignored.  If you want a different behavior
    you can set `errors` to ``'replace'`` or ``'strict'``.

    :param s: The string to unquote.
    :param charset: the charset of the query string.  If set to `None`
        no decoding will take place.
    :param errors: The error handling for the `charset` decoding.

    .. deprecated:: 2.3
        Will be removed in Werkzeug 2.4. Use ``urllib.parse.unquote_plus`` instead.
    """
    if isinstance(s, str):
        s = s.replace("+", " ")
    else:
        s = s.replace(b"+", b" ")

    return url_unquote(s, charset, errors)
