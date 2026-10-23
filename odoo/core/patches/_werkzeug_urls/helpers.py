"""Helpers of the URL functions: the checks of the strings and their encoding."""

from __future__ import annotations

import operator
import sys
import typing as t


if t.TYPE_CHECKING:
    pass


def _check_str_tuple(value: t.Tuple[t.AnyStr, ...]) -> None:
    """Ensure tuple items are all strings or all bytes."""
    if not value:
        return

    item_type = str if isinstance(value[0], str) else bytes

    if any(not isinstance(item, item_type) for item in value):
        raise TypeError(f"Cannot mix str and bytes arguments (got {value!r})")


def _make_encode_wrapper(reference: t.AnyStr) -> t.Callable[[str], t.AnyStr]:
    """Create a function that will be called with a string argument. If
    the reference is bytes, values will be encoded to bytes.
    """
    if isinstance(reference, str):
        return lambda x: x

    return operator.methodcaller("encode", "latin1")


_default_encoding = sys.getdefaultencoding()


def _to_str(
    x: t.Optional[t.Any],
    charset: t.Optional[str] = _default_encoding,
    errors: str = "strict",
    allow_none_charset: bool = False,
):
    if x is None or isinstance(x, str):
        return x

    if not isinstance(x, (bytes, bytearray)):
        return str(x)

    if charset is None:
        if allow_none_charset:
            return x

    return x.decode(charset, errors)  # type: ignore
