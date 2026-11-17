"""The URL classes of werkzeug 2.3, and the parsing of the URLs."""

from __future__ import annotations

import contextlib
import os
import typing as t
from werkzeug.urls import _decode_idna

from .charsets import _scheme_re
from .helpers import _check_str_tuple, _make_encode_wrapper, _to_str
from .query import _url_unquote_legacy, url_decode
from .quote import url_quote, url_unquote

class _URLTuple(t.NamedTuple):
    scheme: str
    netloc: str
    path: str
    query: str
    fragment: str

if t.TYPE_CHECKING:
    from werkzeug import datastructures as ds


class BaseURL(_URLTuple):
    """Superclass of :py:class:`URL` and :py:class:`BytesURL`.

    .. deprecated:: 2.3
        Will be removed in Werkzeug 2.4. Use the ``urllib.parse`` library instead.
    """

    __slots__ = ()
    _at: str
    _colon: str
    _lbracket: str
    _rbracket: str

    def __new__(cls, *args: t.Any, **kwargs: t.Any) -> BaseURL:  # noqa: PYI034
        return super().__new__(cls, *args, **kwargs)

    def __str__(self) -> str:
        return self.to_url()

    def replace(self, **kwargs: t.Any) -> BaseURL:
        """Return an URL with the same values, except for those parameters
        given new values by whichever keyword arguments are specified."""
        return self._replace(**kwargs)

    @property
    def host(self) -> str | None:
        """The host part of the URL if available, otherwise `None`.  The
        host is either the hostname or the IP address mentioned in the
        URL.  It will not contain the port.
        """
        return self._split_host()[0]

    @property
    def ascii_host(self) -> str | None:
        """Works exactly like :attr:`host` but will return a result that
        is restricted to ASCII.  If it finds a netloc that is not ASCII
        it will attempt to idna decode it.  This is useful for socket
        operations when the URL might include internationalized characters.
        """
        rv = self.host
        if rv is not None and isinstance(rv, str):
            with contextlib.suppress(UnicodeError):
                rv = rv.encode("idna").decode("ascii")
        return rv

    @property
    def port(self) -> int | None:
        """The port in the URL as an integer if it was present, `None`
        otherwise.  This does not fill in default ports.
        """
        try:
            rv = int(_to_str(self._split_host()[1]))
            if 0 <= rv <= 65535:
                return rv
        except (ValueError, TypeError):
            pass
        return None

    @property
    def auth(self) -> str | None:
        """The authentication part in the URL if available, `None`
        otherwise.
        """
        return self._split_netloc()[0]

    @property
    def username(self) -> str | None:
        """The username if it was part of the URL, `None` otherwise.
        This undergoes URL decoding and will always be a string.
        """
        rv = self._split_auth()[0]
        if rv is not None:
            return _url_unquote_legacy(rv)
        return None

    @property
    def raw_username(self) -> str | None:
        """The username if it was part of the URL, `None` otherwise.
        Unlike :attr:`username` this one is not being decoded.
        """
        return self._split_auth()[0]

    @property
    def password(self) -> str | None:
        """The password if it was part of the URL, `None` otherwise.
        This undergoes URL decoding and will always be a string.
        """
        rv = self._split_auth()[1]
        if rv is not None:
            return _url_unquote_legacy(rv)
        return None

    @property
    def raw_password(self) -> str | None:
        """The password if it was part of the URL, `None` otherwise.
        Unlike :attr:`password` this one is not being decoded.
        """
        return self._split_auth()[1]

    def decode_query(self, *args: t.Any, **kwargs: t.Any) -> ds.MultiDict[str, str]:
        """Decodes the query part of the URL.  Ths is a shortcut for
        calling :func:`url_decode` on the query argument.  The arguments and
        keyword arguments are forwarded to :func:`url_decode` unchanged.
        """
        return url_decode(self.query, *args, **kwargs)

    def join(self, *args: t.Any, **kwargs: t.Any) -> BaseURL:
        """Joins this URL with another one.  This is just a convenience
        function for calling into :meth:`url_join` and then parsing the
        return value again.
        """
        return url_parse(url_join(self, *args, **kwargs))

    def to_url(self) -> str:
        """Returns a URL string or bytes depending on the type of the
        information stored.  This is just a convenience function
        for calling :meth:`url_unparse` for this URL.
        """
        return url_unparse(self)

    def encode_netloc(self) -> str:
        """Encodes the netloc part to an ASCII safe URL as bytes."""
        rv = self.ascii_host or ""
        if ":" in rv:
            rv = f"[{rv}]"
        port = self.port
        if port is not None:
            rv = f"{rv}:{port}"
        auth = ":".join(
            filter(
                None,
                [
                    url_quote(self.raw_username or "", "utf-8", "strict", "/:%"),
                    url_quote(self.raw_password or "", "utf-8", "strict", "/:%"),
                ],
            )
        )
        if auth:
            rv = f"{auth}@{rv}"
        return rv

    def decode_netloc(self) -> str:
        """Decodes the netloc part into a string."""
        host = self.host or ""

        if isinstance(host, bytes):
            host = host.decode()

        rv = _decode_idna(host)

        if ":" in rv:
            rv = f"[{rv}]"
        port = self.port
        if port is not None:
            rv = f"{rv}:{port}"
        auth = ":".join(
            filter(
                None,
                [
                    _url_unquote_legacy(self.raw_username or "", "/:%@"),
                    _url_unquote_legacy(self.raw_password or "", "/:%@"),
                ],
            )
        )
        if auth:
            rv = f"{auth}@{rv}"
        return rv

    def get_file_location(
        self, pathformat: str | None = None
    ) -> tuple[str | None, str | None]:
        """Returns a tuple with the location of the file in the form
        ``(server, location)``.  If the netloc is empty in the URL or
        points to localhost, it's represented as ``None``.

        The `pathformat` by default is autodetection but needs to be set
        when working with URLs of a specific system.  The supported values
        are ``'windows'`` when working with Windows or DOS paths and
        ``'posix'`` when working with posix paths.

        If the URL does not point to a local file, the server and location
        are both represented as ``None``.

        :param pathformat: The expected format of the path component.
                           Currently ``'windows'`` and ``'posix'`` are
                           supported.  Defaults to ``None`` which is
                           autodetect.
        """
        if self.scheme != "file":
            return None, None

        path = url_unquote(self.path)
        host = self.netloc or None

        if pathformat is None:
            if os.name == "nt":
                pathformat = "windows"
            else:
                pathformat = "posix"

        if pathformat == "windows":
            if path[:1] == "/" and path[1:2].isalpha() and path[2:3] in "|:":
                path = f"{path[1:2]}:{path[3:]}"
            windows_share = path[:3] in ("\\" * 3, "/" * 3)
            import ntpath

            path = ntpath.normpath(path)
            # Windows shared drives are represented as ``\\host\\directory``.
            # That results in a URL like ``file://///host/directory``, and a
            # path like ``///host/directory``. We need to special-case this
            # because the path contains the hostname.
            if windows_share and host is None:
                parts = path.lstrip("\\").split("\\", 1)
                if len(parts) == 2:
                    host, path = parts
                else:
                    host = parts[0]
                    path = ""
        elif pathformat == "posix":
            import posixpath

            path = posixpath.normpath(path)
        else:
            raise TypeError(f"Invalid path format {pathformat!r}")

        if host in ("127.0.0.1", "::1", "localhost"):
            host = None

        return host, path

    def _split_netloc(self) -> tuple[str | None, str]:
        if self._at in self.netloc:
            auth, _, netloc = self.netloc.partition(self._at)
            return auth, netloc
        return None, self.netloc

    def _split_auth(self) -> tuple[str | None, str | None]:
        auth = self._split_netloc()[0]
        if not auth:
            return None, None
        if self._colon not in auth:
            return auth, None

        username, _, password = auth.partition(self._colon)
        return username, password

    def _split_host(self) -> tuple[str | None, str | None]:
        rv = self._split_netloc()[1]
        if not rv:
            return None, None

        if not rv.startswith(self._lbracket):
            if self._colon in rv:
                host, _, port = rv.partition(self._colon)
                return host, port
            return rv, None

        idx = rv.find(self._rbracket)
        if idx < 0:
            return rv, None

        host = rv[1:idx]
        rest = rv[idx + 1 :]
        if rest.startswith(self._colon):
            return host, rest[1:]
        return host, None


class URL(BaseURL):
    """Represents a parsed URL.  This behaves like a regular tuple but
    also has some extra attributes that give further insight into the
    URL.

    .. deprecated:: 2.3
        Will be removed in Werkzeug 2.4. Use the ``urllib.parse`` library instead.
    """

    __slots__ = ()
    _at = "@"
    _colon = ":"
    _lbracket = "["
    _rbracket = "]"

    def encode(self, charset: str = "utf-8", errors: str = "replace") -> BytesURL:
        """Encodes the URL to a tuple made out of bytes.  The charset is
        only being used for the path, query and fragment.
        """
        return BytesURL(
            self.scheme.encode("ascii"),
            self.encode_netloc(),
            self.path.encode(charset, errors),
            self.query.encode(charset, errors),
            self.fragment.encode(charset, errors),
        )


class BytesURL(BaseURL):
    """Represents a parsed URL in bytes.

    .. deprecated:: 2.3
        Will be removed in Werkzeug 2.4. Use the ``urllib.parse`` library instead.
    """

    __slots__ = ()
    _at = b"@"  # type: ignore
    _colon = b":"  # type: ignore
    _lbracket = b"["  # type: ignore
    _rbracket = b"]"  # type: ignore

    def __str__(self) -> str:
        return self.to_url().decode("utf-8", "replace")  # type: ignore

    def encode_netloc(self) -> bytes:  # type: ignore
        """Returns the netloc unchanged as bytes."""
        return self.netloc  # type: ignore

    def decode(self, charset: str = "utf-8", errors: str = "replace") -> URL:
        """Decodes the URL to a tuple made out of strings.  The charset is
        only being used for the path, query and fragment.
        """
        return URL(
            self.scheme.decode("ascii"),  # type: ignore
            self.decode_netloc(),
            self.path.decode(charset, errors),  # type: ignore
            self.query.decode(charset, errors),  # type: ignore
            self.fragment.decode(charset, errors),  # type: ignore
        )




def url_parse(
    url: str, scheme: str | None = None, allow_fragments: bool = True
) -> BaseURL:
    """Parses a URL from a string into a :class:`URL` tuple.  If the URL
    is lacking a scheme it can be provided as second argument. Otherwise,
    it is ignored.  Optionally fragments can be stripped from the URL
    by setting `allow_fragments` to `False`.

    The inverse of this function is :func:`url_unparse`.

    :param url: the URL to parse.
    :param scheme: the default schema to use if the URL is schemaless.
    :param allow_fragments: if set to `False` a fragment will be removed
                            from the URL.

    .. deprecated:: 2.3
        Will be removed in Werkzeug 2.4. Use ``urllib.parse.urlsplit`` instead.
    """
    s = _make_encode_wrapper(url)
    is_text_based = isinstance(url, str)

    if scheme is None:
        scheme = s("")
    netloc = query = fragment = s("")
    i = url.find(s(":"))
    if i > 0 and _scheme_re.match(_to_str(url[:i], errors="replace")):
        # make sure "iri" is not actually a port number (in which case
        # "scheme" is really part of the path)
        rest = url[i + 1 :]
        if not rest or any(c not in s("0123456789") for c in rest):
            # not a port number
            scheme, url = url[:i].lower(), rest

    if url[:2] == s("//"):
        delim = len(url)
        for c in s("/?#"):
            wdelim = url.find(c, 2)
            if wdelim >= 0:
                delim = min(delim, wdelim)
        netloc, url = url[2:delim], url[delim:]
        if (s("[") in netloc and s("]") not in netloc) or (
            s("]") in netloc and s("[") not in netloc
        ):
            raise ValueError("Invalid IPv6 URL")

    if allow_fragments and s("#") in url:
        url, fragment = url.split(s("#"), 1)
    if s("?") in url:
        url, query = url.split(s("?"), 1)

    result_type = URL if is_text_based else BytesURL

    return result_type(scheme, netloc, url, query, fragment)


def url_unparse(components: tuple[str, str, str, str, str]) -> str:
    """The reverse operation to :meth:`url_parse`.  This accepts arbitrary
    as well as :class:`URL` tuples and returns a URL as a string.

    :param components: the parsed URL as tuple which should be converted
                       into a URL string.

    .. deprecated:: 2.3
        Will be removed in Werkzeug 2.4. Use ``urllib.parse.urlunsplit`` instead.
    """

    _check_str_tuple(components)
    scheme, netloc, path, query, fragment = components
    s = _make_encode_wrapper(scheme)
    url = s("")

    # We generally treat file:///x and file:/x the same which is also
    # what browsers seem to do.  This also allows us to ignore a schema
    # register for netloc utilization or having to differentiate between
    # empty and missing netloc.
    if netloc or (scheme and path.startswith(s("/"))):
        if path and path[:1] != s("/"):
            path = s("/") + path
        url = s("//") + (netloc or s("")) + path
    elif path:
        url += path
    if scheme:
        url = scheme + s(":") + url
    if query:
        url = url + s("?") + query
    if fragment:
        url = url + s("#") + fragment
    return url


def url_join(
    base: str | tuple[str, str, str, str, str],
    url: str | tuple[str, str, str, str, str],
    allow_fragments: bool = True,
) -> str:
    """Join a base URL and a possibly relative URL to form an absolute
    interpretation of the latter.

    :param base: the base URL for the join operation.
    :param url: the URL to join.
    :param allow_fragments: indicates whether fragments should be allowed.

    .. deprecated:: 2.3
        Will be removed in Werkzeug 2.4. Use ``urllib.parse.urljoin`` instead.
    """
    if isinstance(base, tuple):
        base = url_unparse(base)
    if isinstance(url, tuple):
        url = url_unparse(url)

    _check_str_tuple((base, url))
    s = _make_encode_wrapper(base)

    if not base:
        return url
    if not url:
        return base

    bscheme, bnetloc, bpath, bquery, _bfragment = url_parse(
        base, allow_fragments=allow_fragments
    )
    scheme, netloc, path, query, fragment = url_parse(url, bscheme, allow_fragments)
    if scheme != bscheme:
        return url
    if netloc:
        return url_unparse((scheme, netloc, path, query, fragment))
    netloc = bnetloc

    if path[:1] == s("/"):
        segments = path.split(s("/"))
    elif not path:
        segments = bpath.split(s("/"))
        if not query:
            query = bquery
    else:
        segments = bpath.split(s("/"))[:-1] + path.split(s("/"))

    # If the rightmost part is "./" we want to keep the slash but
    # remove the dot.
    if segments[-1] == s("."):
        segments[-1] = s("")

    # Resolve ".." and "."
    segments = [segment for segment in segments if segment != s(".")]
    while True:
        i = 1
        n = len(segments) - 1
        while i < n:
            if segments[i] == s("..") and segments[i - 1] not in (s(""), s("..")):
                del segments[i - 1 : i + 1]
                break
            i += 1
        else:
            break

    # Remove trailing ".." if the URL is absolute
    unwanted_marker = [s(""), s("..")]
    while segments[:2] == unwanted_marker:
        del segments[1]

    path = s("/").join(segments)
    return url_unparse((scheme, netloc, path, query, fragment))
