"""The stacks and the clocks of the profiler: the frames, the traces and the time functions."""

import logging
import os
import sys
import threading
import time
from datetime import datetime


_logger = logging.getLogger("'odoo.tools.profiling.profiler'")


real_datetime_now = datetime.now


real_time = time.time.__call__


real_cpu_time = time.thread_time.__call__


def _format_stack(stack):
    return [list(frame) for frame in stack]


# the frames of the profiler itself are skipped, whatever module of the package they are in
_PROFILER_DIR = os.path.dirname(__file__) + os.sep


def get_current_frame(thread=None):
    if thread is not None:
        frame = sys._current_frames()[thread.ident]
    else:
        frame = sys._getframe()
    while frame.f_code.co_filename.startswith(_PROFILER_DIR):
        frame = frame.f_back
    return frame


def _get_stack_trace(frame, limit_frame=None):
    stack = []
    while frame is not None and frame is not limit_frame:
        code = frame.f_code
        line = (code.co_filename, frame.f_lineno, code.co_name, '')
        stack.append(line)
        frame = frame.f_back
    if frame is None and limit_frame:
        _logger.runbot("Limit frame was not found")
    stack.reverse()
    return stack


def stack_size():
    frame = get_current_frame()
    size = 0
    while frame:
        size += 1
        frame = frame.f_back
    return size


def make_session(name=''):
    return f'{real_datetime_now():%Y-%m-%d %H:%M:%S} {name}'


def force_hook():
    """
    Force periodic profiling collectors to generate some stack trace.  This is
    useful before long calls that do not release the GIL, so that the time
    spent in those calls is attributed to a specific stack trace, instead of
    some arbitrary former frame.
    """
    thread = threading.current_thread()
    for func in getattr(thread, 'profile_hooks', ()):
        func()
