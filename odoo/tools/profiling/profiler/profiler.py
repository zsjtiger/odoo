"""The profiler: the execution contexts, the profiles and the nesting of the profilers."""

import json
import logging
import re
import sys
import threading
from contextlib import ExitStack, nullcontext
import psutil
from psycopg2 import OperationalError
from odoo import tools
from odoo.tools import SQL
from odoo.tools.profiling.gc import disabling_gc

from .collectors import Collector
from .stack import _format_stack, _get_stack_trace, get_current_frame, make_session, real_cpu_time, real_datetime_now, real_time, stack_size

_logger = logging.getLogger("'odoo.tools.profiling.profiler'")


class ExecutionContext:
    """
    Add some context on thread at current call stack level.
    This context stored by collector beside stack and is used by Speedscope
    to add a level to the stack with this information.
    """
    def __init__(self, **context):
        self.context = context
        self.previous_context = None

    def __enter__(self):
        current_thread = threading.current_thread()
        self.previous_context = getattr(current_thread, 'exec_context', ())
        current_thread.exec_context = self.previous_context + ((stack_size(), self.context),)

    def __exit__(self, *_args):
        threading.current_thread().exec_context = self.previous_context


class Profiler:
    """
    Context manager to use to start the recording of some execution.
    Will save sql and async stack trace by default.
    """
    def __init__(self, collectors=None, db=..., profile_session=None,
                 description=None, disable_gc=False, params=None, log=False):
        """
        :param db: database name to use to save results.
            Will try to define database automatically by default.
            Use value ``None`` to not save results in a database.
        :param collectors: list of string and Collector object Ex: ['sql', PeriodicCollector(interval=0.2)]. Use `None` for default collectors
        :param profile_session: session description to use to reproup multiple profile. use make_session(name) for default format.
        :param description: description of the current profiler Suggestion: (route name/test method/loading module, ...)
        :param disable_gc: flag to disable gc durring profiling (usefull to avoid gc while profiling, especially during sql execution)
        :param params: parameters usable by collectors (like frame interval)
        """
        self.start_time = 0
        self.duration = 0
        self.start_cpu_time = 0
        self.cpu_duration = 0
        self.profile_session = profile_session or make_session()
        self.description = description
        self.init_frame = None
        self.init_stack_trace = None
        self.init_thread = None
        self.disable_gc = disable_gc
        self.filecache = {}
        self.params = params or {}  # custom parameters usable by collectors
        self.profile_id = None
        self.log = log
        self.sub_profilers = []
        self.entry_count_limit = int(self.params.get("entry_count_limit", 0))
        self.time_limit = int(self.params.get("time_limit", 0))
        self.done = False
        self.exit_stack = ExitStack()
        self.process = psutil.Process()
        self.memory_profile = self.params.get("memory_profile", False)
        self.counter = 0

        if db is ...:
            # determine database from current thread
            db = getattr(threading.current_thread(), 'dbname', None)
            if not db:
                # only raise if path is not given and db is not explicitely disabled
                raise Exception('Database name cannot be defined automaticaly. \n Please provide a valid/falsy dbname or path parameter')
        self.db = db

        # collectors
        if collectors is None:
            collectors = ['sql', 'traces_async']
        self.collectors = []
        for collector in collectors:
            if isinstance(collector, str):
                try:
                    collector = Collector.make(collector)
                except Exception:
                    _logger.error("Could not create collector with name %r", collector)
                    continue
            collector.profiler = self
            self.collectors.append(collector)

    def __enter__(self):
        self.init_thread = threading.current_thread()
        try:
            self.init_frame = get_current_frame(self.init_thread)
            self.init_stack_trace = _get_stack_trace(self.init_frame)
        except KeyError:
            # when using thread pools (gevent) the thread won't exist in the current_frames
            # this case is managed by http.py but will still fail when adding a profiler
            # inside a piece of code that may be called by a longpolling route.
            # in this case, avoid crashing the caller and disable all collectors
            self.init_frame = self.init_stack_trace = self.collectors = []
            self.db = self.params = None
            message = "Cannot start profiler, thread not found. Is the thread part of a thread pool?"
            if not self.description:
                self.description = message
            _logger.warning(message)

        if self.description is None:
            frame = self.init_frame
            code = frame.f_code
            self.description = f"{frame.f_code.co_name} ({code.co_filename}:{frame.f_lineno})"
        if self.params:
            self.init_thread.profiler_params = self.params
        if self.disable_gc:
            self.exit_stack.enter_context(disabling_gc())
        self.start_time = real_time()
        self.start_cpu_time = real_cpu_time()
        for collector in self.collectors:
            collector.start()
        return self

    def __exit__(self, *args):
        self.end()

    def end(self):
        if self.done:
            return
        self.done = True
        try:
            for collector in self.collectors:
                collector.stop()
            self.duration = real_time() - self.start_time
            self.cpu_duration = real_cpu_time() - self.start_cpu_time
            self._add_file_lines(self.init_stack_trace)

            if self.db:
                # pylint: disable=import-outside-toplevel
                from odoo.orm.database.sql_db import db_connect  # only import from odoo if/when needed.
                with db_connect(self.db).cursor() as cr:
                    values = {
                        "name": self.description,
                        "session": self.profile_session,
                        "create_date": real_datetime_now(),
                        "init_stack_trace": json.dumps(_format_stack(self.init_stack_trace)),
                        "duration": self.duration,
                        "cpu_duration": self.cpu_duration,
                        "entry_count": self.entry_count(),
                        "sql_count": sum(len(collector.entries) for collector in self.collectors if collector.name == 'sql')
                    }
                    others = {}
                    for collector in self.collectors:
                        if collector.entries:
                            if collector._store == "others":
                                others[collector.name] = json.dumps(collector.entries)
                            else:
                                values[collector.name] = json.dumps(collector.entries)
                    if others:
                        values['others'] = json.dumps(others)
                    query = SQL(
                        "INSERT INTO ir_profile(%s) VALUES %s RETURNING id",
                        SQL(",").join(map(SQL.identifier, values)),
                        tuple(values.values()),
                    )
                    cr.execute(query)
                    self.profile_id = cr.fetchone()[0]
                    _logger.info('ir_profile %s (%s) created', self.profile_id, self.profile_session)
        except OperationalError:
            _logger.exception("Could not save profile in database")
        finally:
            self.exit_stack.close()
            if self.params:
                del self.init_thread.profiler_params
            if self.log:
                _logger.info(self.summary())

    def _get_cm_proxy(self, context_manager=None):
        return Nested(self, context_manager)

    def _add_file_lines(self, stack):
        for index, frame in enumerate(stack):
            (filename, lineno, name, line) = frame
            if line != '':
                continue
            # retrieve file lines from the filecache
            if not lineno:
                continue
            try:
                filelines = self.filecache[filename]
            except KeyError:
                try:
                    with tools.file_open(filename, filter_ext=('.py',)) as f:
                        filelines = f.readlines()
                except (ValueError, FileNotFoundError):  # mainly for <decorator> "filename"
                    filelines = None
                self.filecache[filename] = filelines
            # fill in the line
            if filelines is not None:
                line = filelines[lineno - 1]
                stack[index] = (filename, lineno, name, line)

    def entry_count(self):
        """ Return the total number of entries collected in this profiler. """
        return sum(len(collector.entries) for collector in self.collectors)

    def format_path(self, path):
        """
        Utility function to format a path for this profiler.
        This is mainly useful to uniquify a path between executions.
        """
        return path.format(
            time=real_datetime_now().strftime("%Y%m%d-%H%M%S"),
            len=self.entry_count(),
            desc=re.sub("[^0-9a-zA-Z-]+", "_", self.description)
        )

    def json(self):
        """
        Utility function to generate a json version of this profiler.
        This is useful to write profiling entries into a file, such as::

            with Profiler(db=None) as profiler:
                do_stuff()

            filename = p.format_path('/home/foo/{desc}_{len}.json')
            with open(filename, 'w') as f:
                f.write(profiler.json())
        """
        return json.dumps({
            "name": self.description,
            "session": self.profile_session,
            "create_date": real_datetime_now().strftime("%Y%m%d-%H%M%S"),
            "init_stack_trace": _format_stack(self.init_stack_trace),
            "duration": self.duration,
            "collectors": {collector.name: collector.entries for collector in self.collectors},
        }, indent=4)

    def summary(self):
        result = ''
        for profiler in [self, *self.sub_profilers]:
            for collector in profiler.collectors:
                result += f'\n{self.description}\n{collector.summary()}'
        return result


class Nested:
    """
    Utility to nest another context manager inside a profiler.

    The profiler should only be called directly in the "with" without nesting it
    with ExitStack. If not, the retrieval of the 'init_frame' may be incorrect
    and lead to an error "Limit frame was not found" when profiling. Since the
    stack will ignore all stack frames inside this file, the nested frames will
    be ignored, too. This is also why Nested() does not use
    contextlib.contextmanager.
    """
    def __init__(self, profiler, context_manager=None):
        self._profiler__ = profiler
        self.context_manager = context_manager or nullcontext()

    def __enter__(self):
        self._profiler__.__enter__()
        try:
            return self.context_manager.__enter__()
        except BaseException:
            self._profiler__.__exit__(*sys.exc_info())
            raise

    def __exit__(self, exc_type, exc_value, traceback):
        try:
            return self.context_manager.__exit__(exc_type, exc_value, traceback)
        finally:
            self._profiler__.__exit__(exc_type, exc_value, traceback)
