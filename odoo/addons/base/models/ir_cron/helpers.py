"""The helpers of the cron jobs: the constants, the errors, the completion statuses and the log handler."""

from __future__ import annotations

import contextvars
import copy
import enum
import logging
import os
import typing
from datetime import timedelta
from dateutil.relativedelta import relativedelta
from odoo.modules import Manifest

_logger = logging.getLogger('odoo.addons.base.models.ir_cron')

if typing.TYPE_CHECKING:
    pass


BASE_VERSION = Manifest.for_addon('base')['version']


MAX_FAIL_TIME = timedelta(hours=5)  # chosen with a fair roll of the dice


MIN_RUNS_PER_JOB = 10


MIN_TIME_PER_JOB = 120  # seconds


CONSECUTIVE_TIMEOUT_FOR_FAILURE = 3


MIN_FAILURE_COUNT_BEFORE_DEACTIVATION = 5


MIN_DELTA_BEFORE_DEACTIVATION = timedelta(days=7)


ODOO_NOTIFY_FUNCTION = os.getenv('ODOO_NOTIFY_FUNCTION', 'pg_notify')


class BadVersion(Exception):
    pass


class BadModuleState(Exception):
    pass


_intervalTypes = {
    'days': lambda interval: relativedelta(days=interval),
    'hours': lambda interval: relativedelta(hours=interval),
    'weeks': lambda interval: relativedelta(days=7 * interval),
    'months': lambda interval: relativedelta(months=interval),
    'minutes': lambda interval: relativedelta(minutes=interval),
}


class CompletionStatus(enum.StrEnum):
    FULLY_DONE = 'fully done'
    PARTIALLY_DONE = 'partially done'
    FAILED = 'failed'


class ListLogHandler(logging.Handler):
    def __init__(self, logger, level=logging.NOTSET):
        super().__init__(level)
        self.logger = logger
        self.list_log_handler = contextvars.ContextVar('list_log_handler', default=None)

    def emit(self, record):
        logs = self.list_log_handler.get(None)
        if logs is None:
            return
        record = copy.copy(record)
        logs.append(record)

    def __enter__(self):
        # set a list in the current context
        logs = []
        self.list_log_handler.set(logs)
        self.logger.addHandler(self)
        return logs

    def __exit__(self, *exc):
        self.logger.removeHandler(self)
