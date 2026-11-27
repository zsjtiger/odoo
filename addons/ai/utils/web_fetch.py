# Part of Odoo. See LICENSE file for full copyright and licensing details.
"""Fetch a web page on the server and extract its readable text.

Every URL is checked before a connection is opened, and again for each
redirect target, so that the server cannot be used to reach internal
networks (SSRF). Only http(s) on the default ports is allowed, and the host
must resolve exclusively to public addresses.
"""
import ipaddress
import socket
from urllib import robotparser
from urllib.parse import urljoin, urlsplit

import requests
from lxml import etree
from lxml import html as lxml_html

ALLOWED_SCHEMES = ('http', 'https')
ALLOWED_PORTS = (None, 80, 443)
MAX_REDIRECTS = 5
MAX_BYTES = 5 * 1024 * 1024
TIMEOUT = 10
USER_AGENT = 'Mozilla/5.0 (compatible; OdooAIScraper/1.0)'
TEXT_CONTENT_TYPES = ('text/html', 'application/xhtml+xml', 'text/plain')
_NON_CONTENT_TAGS = ('script', 'style', 'noscript', 'template', 'svg', 'head')


class WebFetchError(Exception):
    """Raised when a page cannot be fetched or has no usable content.

    :param str reason: machine-readable key, one of ``blocked_url``,
        ``robots_disallowed``, ``fetch_failed``, ``too_large``,
        ``unsupported_content``.
    """

    def __init__(self, reason):
        super().__init__(reason)
        self.reason = reason


def _resolve_public_addresses(url):
    """Return the public IP addresses of ``url``'s host, or raise ``blocked_url``.

    :raises WebFetchError: if the scheme, port or any resolved address is not allowed.
    """
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError as e:
        message = 'blocked_url'
        raise WebFetchError(message) from e
    if parts.scheme not in ALLOWED_SCHEMES or not parts.hostname:
        message = 'blocked_url'
        raise WebFetchError(message)
    if parts.username or parts.password or port not in ALLOWED_PORTS:
        message = 'blocked_url'
        raise WebFetchError(message)

    default_port = 443 if parts.scheme == 'https' else 80
    try:
        infos = socket.getaddrinfo(parts.hostname, port or default_port, proto=socket.IPPROTO_TCP)
    except (socket.gaierror, UnicodeError) as e:
        message = 'fetch_failed'
        raise WebFetchError(message) from e

    addresses = set()
    for info in infos:
        address = ipaddress.ip_address(info[4][0])
        if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped:
            address = address.ipv4_mapped
        if not address.is_global:
            message = 'blocked_url'
            raise WebFetchError(message)
        addresses.add(address)
    return addresses


def _get_once(url):
    """Issue one GET request without following redirects and return the response.

    The body is streamed so that ``MAX_BYTES`` can be enforced.
    """
    return requests.get(
        url,
        headers={'User-Agent': USER_AGENT, 'Accept': 'text/html,text/plain;q=0.9,*/*;q=0.5'},
        timeout=TIMEOUT,
        allow_redirects=False,
        stream=True,
    )


def _safe_get(url):
    """GET ``url`` following redirects manually, validating every hop.

    :return: the final response (already checked for status and size) and its body
    :rtype: tuple(requests.Response, bytes)
    """
    current = url
    for _hop in range(MAX_REDIRECTS + 1):
        _resolve_public_addresses(current)
        try:
            response = _get_once(current)
        except requests.RequestException as e:
            message = 'fetch_failed'
            raise WebFetchError(message) from e
        with response:
            if response.status_code in (301, 302, 303, 307, 308):
                location = response.headers.get('Location')
                if not location:
                    message = 'fetch_failed'
                    raise WebFetchError(message)
                current = urljoin(current, location)
                continue
            if response.status_code >= 400:
                message = 'fetch_failed'
                raise WebFetchError(message)
            body = bytearray()
            for chunk in response.iter_content(chunk_size=64 * 1024):
                body.extend(chunk)
                if len(body) > MAX_BYTES:
                    message = 'too_large'
                    raise WebFetchError(message)
            return response, bytes(body)
    message = 'fetch_failed'
    raise WebFetchError(message)


def _is_allowed_by_robots(url):
    """Return whether ``robots.txt`` of the URL's host allows fetching ``url``.

    A missing or unreadable ``robots.txt`` allows everything, as is customary.
    """
    parts = urlsplit(url)
    robots_url = f'{parts.scheme}://{parts.netloc}/robots.txt'
    parser = robotparser.RobotFileParser()
    try:
        _response, body = _safe_get(robots_url)
    except WebFetchError:
        return True
    parser.parse(body.decode('utf-8', errors='replace').splitlines())
    return parser.can_fetch(USER_AGENT, url) or parser.can_fetch('*', url)


def _extract_text(content_type, body):
    """Return the readable text of a fetched body."""
    if content_type == 'text/plain':
        return body.decode('utf-8', errors='replace')
    try:
        tree = lxml_html.document_fromstring(body)
    except (etree.ParserError, ValueError):
        return ''
    for element in list(tree.iter(*_NON_CONTENT_TAGS)):
        element.drop_tree()
    text = tree.text_content()
    return ' '.join(text.split())


def fetch_page_text(url, check_robots_txt=True):
    """Fetch ``url`` and return its readable text.

    :param str url: the page to fetch
    :param bool check_robots_txt: whether ``robots.txt`` must allow the page
    :return: the extracted text (may be empty if the page has no text)
    :rtype: str
    :raises WebFetchError: when the URL is blocked, cannot be fetched or is not text
    """
    if check_robots_txt and not _is_allowed_by_robots(url):
        message = 'robots_disallowed'
        raise WebFetchError(message)
    response, body = _safe_get(url)
    content_type = (response.headers.get('Content-Type') or '').split(';')[0].strip().lower()
    if content_type not in TEXT_CONTENT_TYPES:
        message = 'unsupported_content'
        raise WebFetchError(message)
    return _extract_text(content_type, body)
