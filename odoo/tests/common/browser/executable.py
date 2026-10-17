# Part of Odoo. See LICENSE file for full copyright and licensing details.
"""Lookup of the Chrome executable used by the tests."""

from __future__ import annotations

import os
import platform
import typing
import unittest
from functools import cache
from odoo.tools.misc import find_in_path

if typing.TYPE_CHECKING:
    pass


@cache
def _find_executable():
    browser_bin_path = os.environ.get('ODOO_BROWSER_BIN')  # used for testing specific Chrome builds
    if browser_bin_path and os.path.exists(browser_bin_path):
        return browser_bin_path
    system = platform.system()
    if system == 'Linux':
        for bin_ in ['google-chrome', 'chromium', 'chromium-browser', 'google-chrome-stable']:
            try:
                return find_in_path(bin_)
            except IOError:
                continue

    elif system == 'Darwin':
        bins = [
            '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
            '/Applications/Chromium.app/Contents/MacOS/Chromium',
        ]
        for bin_ in bins:
            if os.path.exists(bin_):
                return bin_

    elif system == 'Windows':
        bins = [
            '%ProgramFiles%\\Google\\Chrome\\Application\\chrome.exe',
            '%ProgramFiles(x86)%\\Google\\Chrome\\Application\\chrome.exe',
            '%LocalAppData%\\Google\\Chrome\\Application\\chrome.exe',
        ]
        for bin_ in bins:
            bin_ = os.path.expandvars(bin_)
            if os.path.exists(bin_):
                return bin_

    raise unittest.SkipTest("Chrome executable not found")
