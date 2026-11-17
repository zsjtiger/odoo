# Part of Odoo. See LICENSE file for full copyright and licensing details.
"""The logging helpers: muting and lowering the loggers, and the traceback records."""

from __future__ import annotations
import logging
import typing
from functools import wraps

if typing.TYPE_CHECKING:
    pass


_logger = logging.getLogger('odoo.tools.misc')


class mute_logger(logging.Handler):
    """Temporary suppress the logging.

    Can be used as context manager or decorator::

        @mute_logger('odoo.plic.ploc')
        def do_stuff():
            blahblah()

        with mute_logger('odoo.foo.bar'):
            do_suff()
    """
    def __init__(self, *loggers):
        super().__init__()
        self.loggers = loggers
        self.old_params = {}

    def __enter__(self):
        for logger_name in self.loggers:
            logger = logging.getLogger(logger_name)
            self.old_params[logger_name] = (logger.handlers, logger.propagate)
            logger.propagate = False
            logger.handlers = [self]

    def __exit__(self, exc_type=None, exc_val=None, exc_tb=None):
        for logger_name in self.loggers:
            logger = logging.getLogger(logger_name)
            logger.handlers, logger.propagate = self.old_params[logger_name]

    def __call__(self, func):
        @wraps(func)
        def deco(*args, **kwargs):
            with self:
                return func(*args, **kwargs)
        return deco

    def emit(self, record):
        pass


class lower_logging(logging.Handler):
    """Temporary lower the max logging level.
    """
    def __init__(self, max_level, to_level=None):
        super().__init__()
        self.old_handlers = None
        self.old_propagate = None
        self.had_error_log = False
        self.max_level = max_level
        self.to_level = to_level or max_level

    def __enter__(self):
        logger = logging.getLogger()
        self.old_handlers = logger.handlers[:]
        self.old_propagate = logger.propagate
        logger.propagate = False
        logger.handlers = [self]
        self.had_error_log = False
        return self

    def __exit__(self, exc_type=None, exc_val=None, exc_tb=None):
        logger = logging.getLogger()
        logger.handlers = self.old_handlers
        logger.propagate = self.old_propagate

    def emit(self, record):
        if record.levelno > self.max_level:
            record.levelname = f'_{record.levelname}'
            record.levelno = self.to_level
            self.had_error_log = True
            if MungedTracebackLogRecord.__base__ is logging.LogRecord:
                MungedTracebackLogRecord.__bases__ = (record.__class__,)
            record.__class__ = MungedTracebackLogRecord

        if logging.getLogger(record.name).isEnabledFor(record.levelno):
            for handler in self.old_handlers:
                if handler.level <= record.levelno:
                    handler.emit(record)


class MungedTracebackLogRecord(logging.LogRecord):
    def getMessage(self):
        return super().getMessage().replace(
            'Traceback (most recent call last):',
            '_Traceback_ (most recent call last):',
        )
