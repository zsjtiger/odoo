# Part of Odoo. See LICENSE file for full copyright and licensing details.
# ruff: noqa: F401
"""The base test case and its helpers, split by concern: the base case itself, the assertions, the patching, the modes of the registry, the records and the matchers. The names are re-exported here."""

from unittest.mock import patch

from odoo.fields import Command

from .base import BaseCase, CrossModule
from .records import RecordCapturer, loaded_demo_data, new_test_user
from .matchers import Approx, Like, QueryLike, WhitespaceInsensitive

__all__ = [
    'Approx',
    'BaseCase',
    'Command',
    'CrossModule',
    'Like',
    'QueryLike',
    'RecordCapturer',
    'WhitespaceInsensitive',
    'loaded_demo_data',
    'new_test_user',
    'patch',
]
