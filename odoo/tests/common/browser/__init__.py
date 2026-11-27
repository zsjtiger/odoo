# Part of Odoo. See LICENSE file for full copyright and licensing details.
# ruff: noqa: F401
"""Headless Chrome browser of the tests, split by concern. The names are re-exported here."""
from .browser import ChromeBrowser
from .events import console_formatter
from .exceptions import ChromeBrowserException
from .executable import _find_executable
from .files import save_test_file
from .process import read_log
from .transport import websocket

__all__ = [
    'ChromeBrowser',
    'ChromeBrowserException',
    'save_test_file',
]
