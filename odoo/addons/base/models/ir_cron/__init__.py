# Part of Odoo. See LICENSE file for full copyright and licensing details.
# ruff: noqa: F401
"""The scheduled actions of the registry: the helpers, the scheduled actions, their triggers and their progress. The names are re-exported here."""

# the helpers first, then the models in the order of their definitions: the order of the classes is the order of their extensions
from .helpers import BASE_VERSION, BadModuleState, BadVersion, CONSECUTIVE_TIMEOUT_FOR_FAILURE, CompletionStatus, ListLogHandler, MAX_FAIL_TIME, MIN_DELTA_BEFORE_DEACTIVATION, MIN_FAILURE_COUNT_BEFORE_DEACTIVATION, MIN_RUNS_PER_JOB, MIN_TIME_PER_JOB, ODOO_NOTIFY_FUNCTION, _intervalTypes, _logger
from .cron import IrCron
from .trigger import IrCronTrigger
from .progress import IrCronProgress
