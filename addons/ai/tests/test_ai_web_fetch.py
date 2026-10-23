# Part of Odoo. See LICENSE file for full copyright and licensing details.
import socket
from unittest.mock import patch

from odoo.tests import BaseCase, tagged

from odoo.addons.ai.utils import web_fetch
from odoo.addons.ai.utils.web_fetch import WebFetchError, fetch_page_text

PUBLIC_IP = '93.184.216.34'
PRIVATE_IPS = ('127.0.0.1', '10.0.0.5', '192.168.1.10', '169.254.169.254', '::1', '::ffff:127.0.0.1', '100.64.0.1')


class FakeResponse:
    def __init__(self, status_code=200, headers=None, body=b''):
        self.status_code = status_code
        self.headers = {'Content-Type': 'text/html; charset=utf-8', **(headers or {})}
        self._body = body

    def iter_content(self, chunk_size=1):
        for i in range(0, len(self._body), chunk_size):
            yield self._body[i:i + chunk_size]

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


@tagged('post_install', '-at_install')
class TestAIWebFetch(BaseCase):

    def _resolve(self, mapping):
        """Return a getaddrinfo replacement resolving hosts from ``mapping`` (host -> IP)."""
        def getaddrinfo(host, port, *args, **kwargs):
            if host not in mapping:
                raise socket.gaierror(f'unknown host {host}')
            ip = mapping[host]
            family = socket.AF_INET6 if ':' in ip else socket.AF_INET
            return [(family, socket.SOCK_STREAM, 6, '', (ip, port))]
        return getaddrinfo

    def _fetch(self, url, responses, mapping=None, **kwargs):
        """Run ``fetch_page_text`` with scripted HTTP responses keyed by URL."""
        mapping = mapping or {'example.com': PUBLIC_IP, 'other.example.com': PUBLIC_IP}
        requested = []

        def get(url, **_kwargs):
            requested.append(url)
            return responses[url]

        with (
            patch.object(web_fetch.socket, 'getaddrinfo', side_effect=self._resolve(mapping)),
            patch.object(web_fetch.requests, 'get', side_effect=get),
        ):
            text = fetch_page_text(url, **kwargs)
        return text, requested

    def _assert_blocked(self, url, mapping=None):
        with self.assertRaises(WebFetchError) as e:
            self._fetch(url, {}, mapping=mapping, check_robots_txt=False)
        self.assertEqual(e.exception.reason, 'blocked_url')

    def test_non_http_schemes_are_blocked(self):
        for url in ('file:///etc/passwd', 'ftp://example.com/file', 'gopher://example.com/'):
            with self.subTest(url=url):
                self._assert_blocked(url)

    def test_credentials_and_non_standard_ports_are_blocked(self):
        for url in ('https://user:secret@example.com/', 'http://example.com:8080/', 'http://example.com:6379/'):
            with self.subTest(url=url):
                self._assert_blocked(url)

    def test_private_addresses_are_blocked(self):
        for ip in PRIVATE_IPS:
            with self.subTest(ip=ip):
                self._assert_blocked('http://internal.example.com/admin', mapping={'internal.example.com': ip})

    def test_host_resolving_to_one_private_address_is_blocked(self):
        # A host with a public and an internal record must not be reachable either.
        def getaddrinfo(host, port, *args, **kwargs):
            return [
                (socket.AF_INET, socket.SOCK_STREAM, 6, '', (PUBLIC_IP, port)),
                (socket.AF_INET, socket.SOCK_STREAM, 6, '', ('10.0.0.1', port)),
            ]

        with patch.object(web_fetch.socket, 'getaddrinfo', side_effect=getaddrinfo):
            with self.assertRaises(WebFetchError) as e:
                fetch_page_text('https://example.com/', check_robots_txt=False)
        self.assertEqual(e.exception.reason, 'blocked_url')

    def test_unresolvable_host_is_a_fetch_failure(self):
        with self.assertRaises(WebFetchError) as e:
            self._fetch('https://unknown.example.com/', {}, mapping={}, check_robots_txt=False)
        self.assertEqual(e.exception.reason, 'fetch_failed')

    def test_redirect_to_private_address_is_blocked(self):
        responses = {
            'https://example.com/start': FakeResponse(302, {'Location': 'http://internal.example.com/secret'}),
        }
        mapping = {'example.com': PUBLIC_IP, 'internal.example.com': '10.0.0.5'}
        with self.assertRaises(WebFetchError) as e:
            self._fetch('https://example.com/start', responses, mapping=mapping, check_robots_txt=False)
        self.assertEqual(e.exception.reason, 'blocked_url')

    def test_redirects_are_followed_one_hop_at_a_time(self):
        responses = {
            'https://example.com/start': FakeResponse(301, {'Location': '/next'}),
            'https://example.com/next': FakeResponse(200, body=b'<html><body><p>Hello world</p></body></html>'),
        }
        text, requested = self._fetch('https://example.com/start', responses, check_robots_txt=False)
        self.assertEqual(text, 'Hello world')
        self.assertEqual(requested, ['https://example.com/start', 'https://example.com/next'])

    def test_redirect_loops_are_bounded(self):
        responses = {
            'https://example.com/a': FakeResponse(302, {'Location': '/b'}),
            'https://example.com/b': FakeResponse(302, {'Location': '/a'}),
        }
        with self.assertRaises(WebFetchError) as e:
            self._fetch('https://example.com/a', responses, check_robots_txt=False)
        self.assertEqual(e.exception.reason, 'fetch_failed')

    def test_text_is_extracted_without_scripts_and_styles(self):
        body = (
            b'<html><head><title>T</title><style>p{color:red}</style></head>'
            b'<body><script>alert(1)</script><p>Visible   text</p><noscript>no</noscript></body></html>'
        )
        responses = {'https://example.com/': FakeResponse(200, body=body)}
        text, _requested = self._fetch('https://example.com/', responses, check_robots_txt=False)
        self.assertEqual(text, 'Visible text')

    def test_oversized_pages_are_rejected(self):
        body = b'a' * (web_fetch.MAX_BYTES + 1)
        responses = {'https://example.com/': FakeResponse(200, body=body)}
        with self.assertRaises(WebFetchError) as e:
            self._fetch('https://example.com/', responses, check_robots_txt=False)
        self.assertEqual(e.exception.reason, 'too_large')

    def test_http_errors_are_fetch_failures(self):
        responses = {'https://example.com/': FakeResponse(404)}
        with self.assertRaises(WebFetchError) as e:
            self._fetch('https://example.com/', responses, check_robots_txt=False)
        self.assertEqual(e.exception.reason, 'fetch_failed')

    def test_binary_content_is_not_processed(self):
        responses = {'https://example.com/': FakeResponse(200, {'Content-Type': 'image/png'}, b'\x89PNG')}
        with self.assertRaises(WebFetchError) as e:
            self._fetch('https://example.com/', responses, check_robots_txt=False)
        self.assertEqual(e.exception.reason, 'unsupported_content')

    def test_robots_txt_disallowing_the_page_blocks_it(self):
        responses = {
            'https://example.com/robots.txt': FakeResponse(200, {'Content-Type': 'text/plain'}, b'User-agent: *\nDisallow: /private\n'),
        }
        with self.assertRaises(WebFetchError) as e:
            self._fetch('https://example.com/private/page', responses, check_robots_txt=True)
        self.assertEqual(e.exception.reason, 'robots_disallowed')

    def test_missing_robots_txt_allows_the_page(self):
        responses = {
            'https://example.com/robots.txt': FakeResponse(404),
            'https://example.com/page': FakeResponse(200, body=b'<p>Allowed</p>'),
        }
        text, _requested = self._fetch('https://example.com/page', responses, check_robots_txt=True)
        self.assertEqual(text, 'Allowed')
