# Part of Odoo. See LICENSE file for full copyright and licensing details.
"""Logging of the Odoo server: formatters, handlers and logger setup.

This module merges the former ``odoo.netsvc``, ``odoo.logging`` and
``odoo.loglevels`` modules, which remain importable under their old names.
"""
import contextlib
import json
import logging
import logging.config
import logging.handlers
import os
import platform
import sys
import threading
import time
import tomllib
import traceback
import warnings
from unittest import mock

from odoo import release, tools
from odoo.tools.misc import exception_to_unicode

# keep the logger name of the former module, used in logging configurations
_logger = logging.getLogger('odoo.netsvc')

__all__ = [  # noqa: RUF022
    "ColoredFormatter",
    "JSONFormatter",
    "PostgreSQLHandler",
    'BLACK', 'RED', 'GREEN', 'YELLOW', 'BLUE', 'MAGENTA', 'CYAN', 'WHITE', 'HIGH_INTENSITY', 'DEFAULT',
    'HI_BLACK', 'HI_RED', 'HI_GREEN', 'HI_YELLOW', 'HI_BLUE', 'HI_MAGENTA', 'HI_CYAN', 'HI_WHITE',
    "RESET_SEQ", "COLOR_SEQ", "BOLD_SEQ", "COLOR_PATTERN", "TRUE_COLOR_PATTERN",
    "LEVEL_COLOR_MAPPING", "PID_COLORS",
    "LOG_NOTSET", "LOG_DEBUG", "LOG_INFO", "LOG_WARNING", "LOG_ERROR", "LOG_CRITICAL",
    "exception_to_unicode", "LogRecord", "init_logger",
]


class PostgreSQLHandler(logging.Handler):
    """ PostgreSQL Logging Handler will store logs in the database, by default
    the current database, can be set using --log-db=DBNAME
    """

    def __init__(self, log_db):
        super().__init__()
        self._support_metadata = False
        if log_db == '%d':
            self._log_db = None
        else:
            self._log_db = log_db
            with contextlib.suppress(Exception), tools.mute_logger('odoo.sql_db'), _db_connect(self._log_db).cursor() as cr:
                cr.execute("""SELECT 1 FROM information_schema.columns WHERE table_name='ir_logging' and column_name='metadata' AND table_schema = current_schema""")
                self._support_metadata = bool(cr.fetchone())

    def emit(self, record):
        ct = threading.current_thread()
        ct_db = getattr(ct, 'dbname', None)
        dbname = self._log_db or ct_db
        if not dbname:
            return
        with contextlib.suppress(Exception), tools.mute_logger('odoo.sql_db'), _db_connect(dbname).cursor() as cr:
            # preclude risks of deadlocks
            cr.execute("SET LOCAL statement_timeout = 1000")
            msg = str(record.msg)
            if record.args:
                msg = msg % record.args
            traceback = getattr(record, 'exc_text', '')
            if traceback:
                msg = f"{msg}\n{traceback}"
            # we do not use record.levelname because it may have been changed by ColoredFormatter.
            levelname = logging.getLevelName(record.levelno)

            val = ('server', ct_db, record.name, levelname, msg, record.pathname, record.lineno, record.funcName)

            if self._support_metadata and record.test:
                cr.execute("""
                    INSERT INTO ir_logging(create_date, type, dbname, name, level, message, path, line, func, metadata)
                    VALUES (NOW() at time zone 'UTC', %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """, (*val, json.dumps({'test': record.test})))
                return

            cr.execute("""
                INSERT INTO ir_logging(create_date, type, dbname, name, level, message, path, line, func)
                VALUES (NOW() at time zone 'UTC', %s, %s, %s, %s, %s, %s, %s, %s)
            """, val)


BLACK, RED, GREEN, YELLOW, BLUE, MAGENTA, CYAN, WHITE, HIGH_INTENSITY, DEFAULT = range(10)
HI_BLACK, HI_RED, HI_GREEN, HI_YELLOW, HI_BLUE, HI_MAGENTA, HI_CYAN, HI_WHITE = range(
    BLACK + HIGH_INTENSITY, WHITE + HIGH_INTENSITY + 1)
# The background is set with 40 plus the number of the color, and the foreground with 30
# These are the sequences needed to get colored output
RESET_SEQ = "\033[0m"
COLOR_SEQ = "\033[1;%dm"
BOLD_SEQ = "\033[1m"
COLOR_PATTERN = f"{COLOR_SEQ}{COLOR_SEQ}%s{RESET_SEQ}"
TRUE_COLOR_PATTERN = f"\033[38;5;%dm%s{RESET_SEQ}"
LEVEL_COLOR_MAPPING = {
    logging.DEBUG: (BLUE, DEFAULT),
    logging.INFO: (GREEN, DEFAULT),
    logging.WARNING: (YELLOW, DEFAULT),
    logging.ERROR: (RED, DEFAULT),
    logging.CRITICAL: (WHITE, RED),
}
# all colors but black, grey, silver, WARNING and ERROR; length must be prime.
PID_COLORS = (
    GREEN, BLUE, MAGENTA, CYAN,
    HI_RED, HI_GREEN, HI_YELLOW, HI_BLUE, HI_MAGENTA, HI_CYAN, HI_WHITE,
)


class ColoredPercentStyle(logging.PercentStyle):
    def __init__(self, fmt, colors, *, defaults=None):
        super().__init__(fmt, defaults=defaults)
        self.colors = colors

    def _format(self, record):
        colors = self.colors or tools.config.colors  # tools.config.colors may be updated after the Formatter initialization, so we need to get the latest value
        acc = {}
        fg_color, bg_color = LEVEL_COLOR_MAPPING.get(record.levelno, (GREEN, DEFAULT))
        if colors['loglevel']:
            acc['levelname'] = COLOR_PATTERN % (30 + fg_color, 40 + bg_color, record.levelname)
        if colors['pid']:
            acc['process'] = TRUE_COLOR_PATTERN % (PID_COLORS[record.thread_native % len(PID_COLORS)], record.thread_native)
        values = record.__dict__ | acc if acc else record.__dict__
        return self._fmt % values


class Formatter(logging.Formatter):
    default_format = '%(asctime)s %(process)s %(levelname)s %(dbname)s %(name)s: %(message)s'

    def __init__(self, fmt=None, **kwargs):
        if fmt is None:
            fmt = self.default_format
        super().__init__(fmt=fmt, **kwargs)


class ColoredFormatter(Formatter):
    def __init__(self, fmt=None, datefmt=None, style='%', validate=True, *, defaults=None, colors=None):
        if fmt is None:
            fmt = self.default_format
        fmt = fmt.replace('%(message)s', '%(colored_message)s')
        super().__init__(fmt=fmt, datefmt=datefmt, style=style, validate=validate, defaults=defaults)
        self._style = ColoredPercentStyle(fmt, colors=colors)

    def format(self, record):
        if not hasattr(record, 'colored_message'):
            record.colored_message = record.getMessage()
        return super().format(record)


class JSONFormatter(logging.Formatter):

    DEFAULT_IMPLICIT_RECORD_KEYS = {
        'message',  # prefered to msg and args to have the corrsct args formating
        'test',  # needed on runbot
        'exc_info',  # needed on runbot, concataneted to message implicilty in some cases
    }

    DEFAULT_IGNORED_RECORD_KEYS = {
                'msecs',  # derived from created
                'relativeCreated',  # derived from created
                'asctime',  # derived from created
                'filename',  # derived from pathname
                'module',  # derived from filename (pathname)
                'msg',  # formatted in message
                'args',  # formatted in message
    }

    def __init__(self, *args, record_keys=None, ignore_record_keys=None, additional_record_keys=None, **kwargs):
        """
        :param record_keys: list of keys to include in the json output, if None, all keys are included except those in ignore_record_keys
        :param ignore_record_keys: list of keys to ignore in the json output, if None, a default list of keys is used. Only used if record_keys is None
        :param additional_record_keys: list of additional keys to include in the json output
        """
        super().__init__(*args, **kwargs)
        if record_keys is not None and (ignore_record_keys is not None or additional_record_keys is not None):
            raise ValueError("record_keys is exclusive with ignore_record_keys / additional_record_keys")
        self.record_keys = record_keys
        self.additional_record_keys = set(additional_record_keys) if additional_record_keys else set()
        self.ignore_record_keys = set(ignore_record_keys) if ignore_record_keys else set()

    def format(self, record):
        record_json = {}
        record_keys = self.record_keys
        if record_keys is None:
            record_keys = self._get_default_record_keys(record)
        for key in record_keys:
            if key == 'exc_info':
                if record.exc_info:
                    if not record.exc_text:
                        record.exc_text = self.formatException(record.exc_info)
                    record_json[key] = record.exc_text
            elif key == 'stack_info':  # this case is not 100% necessary but allows to override the default stack_info formatting
                if record.stack_info:
                    record_json[key] = self.formatStack(record.stack_info)
            elif key == 'message':
                record.message = record.getMessage()
                record_json[key] = record.message
            elif key == 'asctime':
                record.asctime = self.formatTime(record, self.datefmt)
                record_json[key] = record.asctime
            else:
                value = getattr(record, key, None)
                if value is not None:
                    record_json[key] = value

        return json.dumps(record_json, default=str)

    def _get_default_record_keys(self, record):
        record_keys = (record.__dict__.keys() | self.DEFAULT_IMPLICIT_RECORD_KEYS) - self.DEFAULT_IGNORED_RECORD_KEYS
        return sorted((record_keys - self.ignore_record_keys) | self.additional_record_keys)


def _db_connect(dbname):
    from odoo.orm.sql_db import db_connect  # noqa: PLC0415
    return db_connect(dbname, allow_uri=True)


LOG_NOTSET = 'notset'
LOG_DEBUG = 'debug'
LOG_INFO = 'info'
LOG_WARNING = 'warn'
LOG_ERROR = 'error'
LOG_CRITICAL = 'critical'

real_time = time.time.__call__  # ensure we have a non patched time when using freezegun


class LogRecord(logging.LogRecord):
    def __init__(self, name, level, pathname, lineno, msg, args, exc_info, func=None, sinfo=None, **kwargs):
        super().__init__(name, level, pathname, lineno, msg, args, exc_info, func=func, sinfo=sinfo, **kwargs)
        self.thread_native = threading.get_native_id()
        self.dbname = getattr(threading.current_thread(), 'dbname', '?')
        from odoo import modules  # noqa: PLC0415
        self.test = None
        if time.time.__call__ != real_time:
            self.faked_created = self.created
            self.created = real_time()
        if modules.module.current_test:
            with contextlib.suppress(Exception):
                self.test = modules.module.current_test.get_log_metadata(self)

showwarning = None
def init_logger():
    global showwarning  # noqa: PLW0603
    if logging.getLogRecordFactory() is LogRecord:
        return

    logging.setLogRecordFactory(LogRecord)

    logging.captureWarnings(True)
    # must be after `logging.captureWarnings` so we override *that* instead of
    # the other way around
    showwarning = warnings.showwarning
    warnings.showwarning = showwarning_with_traceback

    # enable deprecation warnings (disabled by default)
    warnings.simplefilter('default', category=DeprecationWarning)
    warnings.filterwarnings('default', category=PendingDeprecationWarning)
    # https://github.com/urllib3/urllib3/issues/2680
    warnings.filterwarnings('ignore', r'^\'urllib3.contrib.pyopenssl\' module is deprecated.+', category=DeprecationWarning)
    # ignore a bunch of warnings we can't really fix ourselves
    for module in [
        'babel.util', # deprecated parser module, no release yet
        'zeep.loader',# zeep using defusedxml.lxml
        'reportlab.lib.rl_safe_eval',# reportlab importing ABC from collections
        'ofxparse',# ofxparse importing ABC from collections
        'astroid',  # deprecated imp module (fixed in 2.5.1)
        'requests_toolbelt', # importing ABC from collections (fixed in 0.9)
    ]:
        warnings.filterwarnings('ignore', category=DeprecationWarning, module=module)

    # rsjmin triggers this with Python 3.10+ (that warning comes from the C code and has no `module`)
    warnings.filterwarnings('ignore', r'^PyUnicode_FromUnicode\(NULL, size\) is deprecated', category=DeprecationWarning)
    # the SVG guesser thing always compares str and bytes, ignore it
    warnings.filterwarnings('ignore', category=BytesWarning, module='odoo.tools.image')
    # reportlab does a bunch of bytes/str mixing in a hashmap
    warnings.filterwarnings('ignore', category=BytesWarning, module='reportlab.platypus.paraparser')

    # need to be adapted later but too muchwork for this pr.
    warnings.filterwarnings('ignore', r'^datetime.datetime.utcnow\(\) is deprecated and scheduled for removal in a future version.*', category=DeprecationWarning)

    # pkg_ressouce is used in google-auth < 1.23.0 (removed in https://github.com/googleapis/google-auth-library-python/pull/596)
    # unfortunately, in ubuntu jammy and noble, the google-auth version is 1.5.1
    # starting from noble, the default pkg_ressource version emits a warning on import, triggered when importing
    # google-auth
    warnings.filterwarnings('ignore', r'pkg_resources is deprecated as an API.+', category=DeprecationWarning)
    warnings.filterwarnings('ignore', r'Deprecated call to \`pkg_resources.declare_namespace.+', category=DeprecationWarning)

    # This warning is triggered library only during the python precompilation which does not occur on readonly filesystem
    warnings.filterwarnings("ignore", r'invalid escape sequence', category=DeprecationWarning, module=".*vobject")
    warnings.filterwarnings("ignore", r'invalid escape sequence', category=SyntaxWarning, module=".*vobject")
    from odoo.tools.translate import resetlocale  # noqa: PLC0415
    resetlocale()

    if conf := tools.config['log_config']:
        with open(conf, 'rb') as fobj:
            if conf.endswith('.toml'):
                conf = tomllib.load(fobj)
            else:
                conf = json.load(fobj)
            # since we create a bunch of loggers at import, if this is enabled
            # (default) none of the loggers created before loading the config
            # will fire unless they're forcefully enabled in the config file
            conf['disable_existing_loggers'] = False
        logging.config.dictConfig(conf)
        if not conf.get('keep_odoo_default', False):
            return

    # Normal Handler on stderr
    handler = logging.StreamHandler()
    formatter = ColoredFormatter()

    if tools.config['syslog']:
        # SysLog Handler
        if os.name == 'nt':
            handler = logging.handlers.NTEventLogHandler(f"{release.description} {release.version}")
        elif platform.system() == 'Darwin':
            handler = logging.handlers.SysLogHandler('/var/run/log')
        else:
            handler = logging.handlers.SysLogHandler('/dev/log')
        formatter = logging.Formatter(f'{release.description} {release.version}:%(dbname)s:%(levelname)s:%(name)s:%(message)s')

    elif tools.config['logfile']:
        # LogFile Handler
        logf = tools.config['logfile']
        try:
            # We check we have the right location for the log files
            dirname = os.path.dirname(logf)
            if dirname and not os.path.isdir(dirname):
                os.makedirs(dirname)
            if os.name == 'posix':
                handler = logging.handlers.WatchedFileHandler(logf)
            else:
                handler = logging.FileHandler(logf)
        except Exception:
            sys.stderr.write("ERROR: couldn't create the logfile directory. Logging to the standard output.\n")

    handler.setFormatter(formatter)
    logging.getLogger().addHandler(handler)

    if log_db := tools.config['log_db']:
        db_levels = {
            'debug': logging.DEBUG,
            'info': logging.INFO,
            'warning': logging.WARNING,
            'error': logging.ERROR,
            'critical': logging.CRITICAL,
        }
        postgresqlHandler = PostgreSQLHandler(log_db)
        postgresqlHandler.setLevel(int(db_levels.get(tools.config['log_db_level'], tools.config['log_db_level'])))
        logging.getLogger().addHandler(postgresqlHandler)

    # Configure loggers levels
    pseudo_config = PSEUDOCONFIG_MAPPER.get(tools.config['log_level'], [])

    logconfig = tools.config['log_handler']

    logging_configurations = DEFAULT_LOG_CONFIGURATION + pseudo_config + logconfig
    for logconfig_item in logging_configurations:
        loggername, level = logconfig_item.strip().split(':')
        level = getattr(logging, level, logging.INFO)
        logger = logging.getLogger(loggername)
        logger.setLevel(level)

    for logconfig_item in logging_configurations:
        _logger.debug('logger level set: "%s"', logconfig_item)

    if tools.config['syslog']:
        # temporarily restore normal to skip useless stracktrace
        with mock.patch.object(warnings, "showwarning", showwarning):
            warnings.warn_explicit(
                "The --syslog option is deprecated since Odoo 20, "
                "switch to --log-config and configure a syslog handler.",
                category=DeprecationWarning,
                filename='<argv>',
                lineno=1,
            )

DEFAULT_LOG_CONFIGURATION = [
    ':INFO',
]
PSEUDOCONFIG_MAPPER = {
    'debug': ['odoo:DEBUG', 'odoo.sql_db:INFO'],
    'debug_sql': ['odoo.sql_db:DEBUG'],
    'info': [],
    'runbot': ['odoo:RUNBOT'],
    'warn': ['odoo:WARNING'],
    'error': ['odoo:ERROR'],
    'critical': ['odoo:CRITICAL'],
}

IGNORE = {
    'Comparison between bytes and int', # a.foo != False or some shit, we don't care
}
def showwarning_with_traceback(message, category, filename, lineno, file=None, line=None):
    if category is BytesWarning and message.args[0] in IGNORE:
        return

    # find the stack frame matching (filename, lineno)
    filtered = []
    for frame in traceback.extract_stack():
        if frame.name == '__call__' and frame.filename.endswith('/odoo/http/router.py'):
            # we don't care about the frames above our wsgi entrypoint
            filtered.clear()
        if 'importlib' not in frame.filename:
            filtered.append(frame)
        if frame.filename == filename and frame.lineno == lineno:
            break
    return showwarning(
        message, category, filename, lineno,
        file=file,
        line=''.join(traceback.format_list(filtered))
    )
