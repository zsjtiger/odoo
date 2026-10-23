# Part of Odoo. See LICENSE file for full copyright and licensing details.
# ruff: noqa: F401
"""The environments of the models, split by concern: the environment, the transaction and the caches. The names are re-exported here."""

from .environment import Environment, MAX_FIXPOINT_ITERATIONS
from .transaction import ENVS_SIZE, Transaction, TransactionState, _logger_signaling
from .caches import Cache, CacheLayer, EMPTY_DICT, Starred
