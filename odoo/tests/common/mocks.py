# Part of Odoo. See LICENSE file for full copyright and licensing details.
"""Mocks of the HTTP client that prevent the tests from reaching the network."""

from __future__ import annotations

import json
import typing
from contextlib import AbstractContextManager
from unittest.mock import patch
import requests
from urllib3.util import parse_url

if typing.TYPE_CHECKING:
    pass


class BlockedRequest(requests.exceptions.ConnectionError):
    pass


_super_send = requests.Session.send


class MockHTTPClient(AbstractContextManager):
    """Mock ``requests`` calls and return a fake ``requests.Response``.

    This context manager patches ``requests.sessions.Session.send``.
    Each outgoing request is checked against the match criteria. If it
    matches, the request is recorded in ``calls``, the optional
    ``side_effect`` is executed, and a mocked response is returned. If
    it does not match, the request is delegated to the previously active
    ``send`` (either the real ``requests`` implementation, or an outer
    ``MockHTTPClient`` when you nest mocks), so multiple
    ``MockHTTPClient`` instances can be composed.

    A request matches when all checks pass:

    * ``method`` (if passed): matches the HTTP method (case-insensitive)
    * ``url`` (if passed):  limits which requests this mock will catch.
      Use ``"https://api.example.com/v1/items"`` to match that
      host + path; include more (e.g. a query string) to make it
      stricter. Anything you omit is treated as "don't care" and won't
      affect matching.
    * ``matcher(request)`` (if passed): a custom function predicate for
      anything beyond method/URL (headers, JSON body, etc.).

    The response is built from ``return_status`` and ``return_headers``
    (both can be values or callables).
    The body comes from ``return_json`` (JSON-encoded and defaults
    ``Content-Type`` to ``application/json``) or from ``return_body``
    when ``return_json`` is ``None``.

    Examples
    --------
    Mock an auth flow and return dynamic JSON based on headers

    .. code-block:: python
        def is_body_authorized(req):
            token = req.headers.get('Authorization')
            if token == 'Bearer super-secure-token':
                return "Authorized!"
            return "Not authorized :("

        def check_auth_header(req):
            self.assertIn(
                'Authorization',
                req.headers,
                "Missing Authorization header",
            )

        with (
            MockHTTPClient(
                url='https://auth.example.com/token',
                return_json={'token': 'super-secure-token'},
            ) as auth_mock,
            MockHTTPClient(
                url='https://api.example.com/am-i-authorized',
                return_body=is_body_authorized,
                side_effect=check_auth_header,
            ) as api_mock,
        ):
            token = requests.get(
                'https://auth.example.com/token',
            ).json()['token']
            auth_mock.assert_called_once()

            resp = requests.get(
                'https://api.example.com/am-i-authorized',
                headers={'Authorization': f'Bearer {token}'},
            )
            api_mock.assert_called_once()
            assert resp.text == "Authorized!"
    """

    def __init__(
        self,
        url: str | None = None,
        *,
        method: str | None = None,
        matcher: typing.Callable[[requests.PreparedRequest], bool] | None = None,
        return_status: int | typing.Callable[[requests.PreparedRequest], int] = 200,
        return_json: dict | typing.Callable[[requests.PreparedRequest], dict] | None = None,
        return_body: bytes | str | typing.Callable[[requests.PreparedRequest], bytes | str] | None = None,
        return_headers: dict | typing.Callable[[requests.PreparedRequest], dict] | None = None,
        side_effect: typing.Callable[[requests.PreparedRequest], None] | None = None,
    ):
        self.url = parse_url(url) if url else None
        if url and not self.url.host:
            raise ValueError(f"URL '{url}' is not valid: missing host")
        self.method = method.upper() if method else None
        self.matcher = matcher
        self.return_status = return_status if callable(return_status) else lambda _req: return_status

        self.return_json = None
        if callable(return_json):
            self.return_json = return_json
        elif return_json is not None:
            self.return_json = lambda _req: return_json
        if self.return_json is not None and return_body is not None:
            raise ValueError("Cannot specify both return_json and return_body")

        self.return_body = return_body if callable(return_body) else lambda _req: return_body
        self.return_headers = return_headers if callable(return_headers) else lambda _req: return_headers or {}
        self.side_effect = side_effect
        self.calls = []
        self.super_send = None

    def _request_matches(self, req: requests.PreparedRequest) -> bool:
        if self.method and self.method != req.method.upper():
            return False
        if self.url and req.url:
            request_url = parse_url(req.url)
            if any((
                self.url.scheme and self.url.scheme != request_url.scheme,
                self.url.host and self.url.host != request_url.host,
                self.url.port and self.url.port != request_url.port,
                self.url.path and self.url.path != request_url.path,
                self.url.query and self.url.query != request_url.query,
            )):
                return False
        return self.matcher is None or self.matcher(req)

    def __enter__(self):
        self.super_send = requests.sessions.Session.send
        self.calls = []

        def send(session, req: requests.PreparedRequest, **kw):
            if not self._request_matches(req):
                return self.super_send(session, req, **kw)

            self.calls.append(req)
            if self.side_effect:
                self.side_effect(req)

            resp = requests.Response()
            resp.status_code = self.return_status(req)
            resp.url = req.url or ''
            resp.request = req
            resp.headers.update(self.return_headers(req))
            if self.return_json is not None:
                resp.headers.setdefault('Content-Type', 'application/json')
                resp.encoding = 'utf-8'
                resp._content = json.dumps(self.return_json(req), ensure_ascii=False).encode()
            else:
                return_body = self.return_body(req)
                resp._content = return_body.encode() if isinstance(return_body, str) else return_body or b''

            return resp

        self.patcher = patch.object(requests.sessions.Session, 'send', send)
        self.patcher.start()
        return self

    def __exit__(self, exc_type, exc, tb):
        self.patcher.stop()
        self.super_send = None
        return False

    def __repr__(self) -> str:
        return (
            'MockHTTPClient('
            f'method={str(self.method)!r}, '
            f'url={str(self.url.url) if self.url is not None else None!r}, '
            f'matcher={"set" if self.matcher else None!r}, '
            f'side_effect={"set" if self.side_effect else None!r}, '
            f'body={"json" if self.return_json is not None else "body"!r}, '
            f'calls={len(self.calls)})'
        )

    def assert_called(self, n_times=None):
        if n_times == 0:
            if self.calls:
                raise AssertionError(f"Expected 0 calls. Called {len(self.calls)} times.")
            return

        if not self.calls:
            raise AssertionError("Expected to have been called at least once. No calls were made.")

        if n_times is not None and len(self.calls) != n_times:
            raise AssertionError(f"Expected {n_times} calls. Called {len(self.calls)} times.")

    def assert_called_once(self):
        self.assert_called(n_times=1)

    def assert_not_called(self):
        self.assert_called(n_times=0)
