"""Character sets of the URLs: the safe characters, the hexadecimal digits and the schemes."""

from __future__ import annotations

import re


_scheme_re = re.compile(r"^[a-zA-Z0-9+-.]+$")


_always_safe_chars = (
    "abcdefghijklmnopqrstuvwxyz"
    "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    "0123456789"
    "-._~"
)


_always_safe = frozenset(_always_safe_chars.encode("ascii"))


_hexdigits = "0123456789ABCDEFabcdef"


_hextobyte = {
    f"{a}{b}".encode("ascii"): int(f"{a}{b}", 16)
    for a in _hexdigits
    for b in _hexdigits
}


_bytetohex = [f"%{char:02X}".encode("ascii") for char in range(256)]
