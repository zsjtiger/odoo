"""The collectors of the profiler: the SQL queries and the periodic samples of the stacks."""

import threading

from .stack import _get_stack_trace, get_current_frame, real_time

class Collector:
    """
    Base class for objects that collect profiling data.

    A collector object is used by a profiler to collect profiling data, most
    likely a list of stack traces with time and some context information added
    by ExecutionContext decorator on current thread.

    This is a generic implementation of a basic collector, to be inherited.
    It defines default behaviors for creating an entry in the collector.
    """
    name = None                 # symbolic name of the collector
    _store = name
    _registry = {}              # map collector names to their class

    @classmethod
    def __init_subclass__(cls):
        if cls.name:
            cls._registry[cls.name] = cls
            cls._registry[cls.__name__] = cls

    @classmethod
    def make(cls, name, *args, **kwargs):
        """ Instantiate a collector corresponding to the given name. """
        return cls._registry[name](*args, **kwargs)

    def __init__(self):
        self._processed = False
        self._entries = []
        self.profiler = None

    def start(self):
        """ Start the collector. """

    def stop(self):
        """ Stop the collector. """

    def add(self, entry=None, frame=None, check_limit=True):
        """ Add an entry (dict) to this collector. """
        exceeded_entry_count = bool(self.profiler.entry_count_limit) \
                                and self.profiler.counter >= self.profiler.entry_count_limit
        exceeded_time_limit = bool(self.profiler.time_limit) \
                              and self.profiler.time_limit < real_time() - self.profiler.start_time
        if (
            check_limit
            and exceeded_entry_count
            and exceeded_time_limit
        ):
            self.profiler.end()
            return
        self.profiler.counter += 1
        if entry is None:
            entry = {}
        if 'start' not in entry:
            entry['start'] = real_time()
        if 'stack' not in entry:
            frame = frame or get_current_frame(self.profiler.init_thread)
            entry['stack'] = _get_stack_trace(frame, self.profiler.init_frame)
        if 'exec_context' not in entry:
            entry['exec_context'] = getattr(self.profiler.init_thread, 'exec_context', ())
        self._entries.append(entry)
        return entry

    def post_process(self):
        for entry in self._entries:
            stack = entry.get('stack', [])
            self.profiler._add_file_lines(stack)

    @property
    def entries(self):
        """ Return the entries of the collector after postprocessing. """
        if not self._processed:
            self.post_process()
            self.processed_entries = self._entries
            self._entries = None  # avoid modification after processing
            self._processed = True
        return self.processed_entries

    def summary(self):
        return f"{'='*10} {self.name} {'='*10} \n Entries: {len(self._entries)}"


class SQLCollector(Collector):
    """
    Saves all executed queries in the current thread with the call stack.
    """
    name = 'sql'

    def start(self):
        init_thread = self.profiler.init_thread
        if not hasattr(init_thread, 'query_hooks'):
            init_thread.query_hooks = []
        init_thread.query_hooks.append(self.hook)

    def stop(self):
        self.profiler.init_thread.query_hooks.remove(self.hook)

    def hook(self, cr, query, params, query_start, query_time):
        entry = {
            'query': str(query),
            'full_query': str(cr._format(query, params, color_highlight=False)),
            'start': query_start,
            'time': query_time,
        }
        sample = self.add(entry)

        def update_sample(delay):
            sample['time'] = delay

        return update_sample

    def summary(self):
        total_time = sum(entry['time'] for entry in self._entries) or 1
        sql_entries = ''
        for entry in self._entries:
            sql_entries += f"\n{'-' * 100}'\n'{entry['time']}  {'*' * int(entry['time'] / total_time * 100)}'\n'{entry['full_query']}"
        return super().summary() + sql_entries


class _BasePeriodicCollector(Collector):
    """
    Record execution frames asynchronously at most every `interval` seconds.

    :param interval (float): time to wait in seconds between two samples.
    """
    _min_interval = 0.0001  # minimum interval allowed
    _max_interval = 5    # maximum interval allowed
    _default_interval = 0.001

    def __init__(self, interval=None):  # check duration. dynamic?
        super().__init__()
        self._end_time = real_time()
        self.frame_interval = interval or self._default_interval
        self.__thread = threading.Thread(target=self.run)
        self._stop_event = threading.Event()

    def start(self):
        interval = self.profiler.params.get(f'{self.name}_interval')
        if interval:
            self.frame_interval = min(max(float(interval), self._min_interval), self._max_interval)
        init_thread = self.profiler.init_thread
        if not hasattr(init_thread, 'profile_hooks'):
            init_thread.profile_hooks = []
        init_thread.profile_hooks.append(self.add)
        self._end_time = None
        self.__thread.start()

    def run(self):
        while self._end_time is None:
            self.add()
            self.sleep()

    def sleep(self):
        # Note: This may not be very precise. Most systems will sleep at
        # minimum between 1 and 5 ms. "The suspension time may be longer
        # than requested by an arbitrary amount, because of the scheduling
        # of other activity in the system."
        self._stop_event.wait(self.frame_interval)

    def stop(self):
        self._end_time = real_time()
        self._stop_event.set()
        self._entries.append({'stack': [], 'start': real_time()})  # add final end frame
        if self.__thread.is_alive() and self.__thread is not threading.current_thread():
            self.__thread.join()
        self.profiler.init_thread.profile_hooks.remove(self.add)


class PeriodicCollector(_BasePeriodicCollector):

    name = 'traces_async'

    def __init__(self, interval=None):
        super().__init__(interval)
        self._last_frame_id = 0  # incremental identifier if the frame has been seen
        self._last_time = 0

    def start(self):
        self._memory_profile = self.profiler.memory_profile
        self._process = self.profiler.process
        super().start()

    def add(self, entry=None, frame=None, check_limit=True):
        """ Add an entry (dict) to this collector. """
        now = real_time()
        last_frame_id = self._last_frame_id
        if last_frame_id and (duration := now - self._last_time) > self.frame_interval * 10:
            # The profiler has unexpectedly slept for more than 10 frame intervals. This may
            # happen when calling a C library without releasing the GIL. In that case, the
            # last frame was taken before the call, and the next frame is after the call, and
            # the call itself does not appear in any of those frames: the duration of the call
            # is incorrectly attributed to the last frame.
            self._entries[-1]['stack'].append(('profiling', 0, '⚠ Profiler freezed for %s s' % duration, ''))
        self._last_time = now

        frame = frame or get_current_frame(self.profiler.init_thread)
        frame_locals = frame.f_locals
        if frame_locals.get('$__PeriodicCollectorId') == last_frame_id:
            # don't save if the frame is exactly the same as the previous one.
            return
        frame_locals['$__PeriodicCollectorId'] = self._last_frame_id = last_frame_id + 1
        entry = {'start': now}
        if self._memory_profile:
            entry = {'memory': self._process.memory_info().rss, **(entry or {})}
        super().add(entry, frame, check_limit=check_limit)
