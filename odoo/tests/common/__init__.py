# Part of Odoo. See LICENSE file for full copyright and licensing details.
# ruff: noqa: F401
"""The module :mod:`odoo.tests.common` provides unittest test cases and a few
helpers and classes to write tests.

The names are split by concern in the submodules: ``utils`` (constants and
helpers), ``decorators`` (tags and parametrization), ``locks`` (the locks of the
test registry), ``transaction`` (the transaction test case), ``base`` (the base
test case and the assertion helpers), ``mocks`` (the HTTP mocks), ``browser``
(the headless Chrome) and ``http_case`` (the HTTP test case). The package
re-exports them, so that ``odoo.tests.common`` keeps its names.
"""
from .utils import ADMIN_USER_ID, BROWSER_WAIT, CHECK_BROWSER_ITERATIONS, CHECK_BROWSER_SLEEP, Future, IGNORED_MSGS, can_import, case, freezegun, importlib, re, run, safe_whitelist, str2bool, sys, test_xsd
from .decorators import defaultdict, no_retry, standalone, standalone_tests, tagged, users, warmup, wraps
from .locks import DummyRLock, RegistryRLock
from .mocks import AbstractContextManager, BlockedRequest, MockHTTPClient, parse_url
from .base import Approx, Command, CrossModule, Like, QueryLike, RecordCapturer, WhitespaceInsensitive, loaded_demo_data, new_test_user
from .transaction import BaseCase, CacheLayer, CryptContext, Cursor, LRU, Registry, deepcopy, deque, fields, freeze_time, mute_logger, test_cursor, traceback
from .browser import save_test_file
from .screencast import NoScreencast, Screencaster
from .http_case import ChromeBrowser, ChromeBrowserException, DEFAULT_LANG, DEFAULT_SUCCESS_SIGNAL, DISABLE_TIMEOUTS, ExitStack, HOST, HttpCase, JsonRpcException, OdooHttpSession, Opener, Request, Response, Session, TEST_CURSOR_COOKIE_NAME, TransactionCase, Transport, api, base64, config, contextlib, contextmanager, flushing_cursor, get_db_name, get_default_session, inspect, itertools, json, logging, logout, odoo, os, parse_qsl, patch, profiler, real_time, release_test_lock, request, requests, session_store, shorten, threading, time, typing, update_session_token, urlencode, urljoin, urlsplit, urlunsplit, uuid4, xmlrpclib


# the names of the former module that are used through odoo.tests, the submodules are not exported
__all__ = [
    'ADMIN_USER_ID',
    'Approx',
    'BROWSER_WAIT',
    'BaseCase',
    'BlockedRequest',
    'CHECK_BROWSER_ITERATIONS',
    'CHECK_BROWSER_SLEEP',
    'ChromeBrowser',
    'ChromeBrowserException',
    'Command',
    'CrossModule',
    'DEFAULT_SUCCESS_SIGNAL',
    'DISABLE_TIMEOUTS',
    'DummyRLock',
    'HOST',
    'HttpCase',
    'IGNORED_MSGS',
    'JsonRpcException',
    'Like',
    'MockHTTPClient',
    'NoScreencast',
    'Opener',
    'QueryLike',
    'RecordCapturer',
    'RegistryRLock',
    'Response',
    'Screencaster',
    'TEST_CURSOR_COOKIE_NAME',
    'TransactionCase',
    'Transport',
    'WhitespaceInsensitive',
    'can_import',
    'flushing_cursor',
    'freeze_time',
    'get_db_name',
    'loaded_demo_data',
    'new_test_user',
    'no_retry',
    'patch',
    'release_test_lock',
    'run',
    'save_test_file',
    'standalone',
    'standalone_tests',
    'tagged',
    'test_xsd',
    'users',
    'warmup',
]
