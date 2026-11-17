# Part of Odoo. See LICENSE file for full copyright and licensing details.
"""Code reloading: watch the source files and restart the server when they change."""

import logging
import os
import platform
import threading



from . import common

if os.name == 'posix':
    try:
        import inotify
        from inotify.adapters import InotifyTrees
        from inotify.constants import IN_CREATE, IN_MODIFY, IN_MOVED_TO
        INOTIFY_LISTEN_EVENTS = IN_MODIFY | IN_CREATE | IN_MOVED_TO
    except ImportError:
        inotify = None
else:
    inotify = None

if not inotify:
    try:
        import watchdog
        from watchdog.events import FileCreatedEvent, FileModifiedEvent, FileMovedEvent
        from watchdog.observers import Observer
    except ImportError:
        watchdog = None


_logger = logging.getLogger('odoo.service.server')


# ----------------------------------------------------------
# FileSystem Watcher for autoreload and cache invalidation
# ----------------------------------------------------------

class FSWatcherBase:
    def handle_file(self, path):
        if path.endswith('.py') and not os.path.basename(path).startswith('.~'):
            try:
                with open(path, 'rb') as file:
                    source = file.read() + b'\n'
                compile(source, path, 'exec')
            except OSError:
                _logger.exception("autoreload: python code change detected, OSError for %s", path)
            except SyntaxError:
                _logger.exception("autoreload: python code change detected, SyntaxError in %s", path)
            else:
                if not common.server_phoenix:
                    _logger.info('autoreload: python code updated, autoreload activated')
                    from odoo.service.server import restart  # noqa: PLC0415
                    restart()
                    return True
        return None


class FSWatcherWatchdog(FSWatcherBase):
    def __init__(self):
        self.observer = Observer()
        import odoo.addons  # noqa: PLC0415
        for path in odoo.addons.__path__:
            _logger.info('Watching addons folder %s', path)
            self.observer.schedule(self, path, recursive=True)

    def dispatch(self, event):
        if isinstance(event, (FileCreatedEvent, FileModifiedEvent, FileMovedEvent)):
            if not event.is_directory:
                path = getattr(event, 'dest_path', '') or event.src_path
                self.handle_file(path)

    def start(self):
        self.observer.start()
        _logger.info('AutoReload watcher running with watchdog')

    def stop(self):
        self.observer.stop()
        self.observer.join()


class FSWatcherInotify(FSWatcherBase):
    def __init__(self):
        self.started = False
        # ignore warnings from inotify in case we have duplicate addons paths.
        inotify.adapters._LOGGER.setLevel(logging.ERROR)
        # recreate a list as InotifyTrees' __init__ deletes the list's items
        paths_to_watch = []
        import odoo.addons  # noqa: PLC0415
        for path in odoo.addons.__path__:
            paths_to_watch.append(path)
            _logger.info('Watching addons folder %s', path)
        self.watcher = InotifyTrees(paths_to_watch, mask=INOTIFY_LISTEN_EVENTS, block_duration_s=.5)

    def run(self):
        _logger.info('AutoReload watcher running with inotify')
        dir_creation_events = {'IN_MOVED_TO', 'IN_CREATE'}
        while self.started:
            for event in self.watcher.event_gen(timeout_s=0, yield_nones=False):
                (_, type_names, path, filename) = event
                if 'IN_ISDIR' not in type_names:
                    # despite not having IN_DELETE in the watcher's mask, the
                    # watcher sends these events when a directory is deleted.
                    if 'IN_DELETE' not in type_names:
                        full_path = os.path.join(path, filename)
                        if self.handle_file(full_path):
                            return
                elif dir_creation_events.intersection(type_names):
                    full_path = os.path.join(path, filename)
                    for root, _, files in os.walk(full_path):
                        for file in files:
                            if self.handle_file(os.path.join(root, file)):
                                return

    def start(self):
        self.started = True
        self.thread = threading.Thread(target=self.run, name="odoo.service.autoreload.watcher")
        self.thread.daemon = True
        self.thread.start()

    def stop(self):
        self.started = False
        self.thread.join()
        del self.watcher  # ensures inotify watches are freed up before reexec


def start_watcher():
    """ Start the watcher of the source files for the code autoreload. Return
    it, or None when no watcher module is installed.
    """
    if inotify:
        watcher = FSWatcherInotify()
        watcher.start()
        return watcher
    if watchdog:
        watcher = FSWatcherWatchdog()
        watcher.start()
        return watcher
    if os.name == 'posix' and platform.system() != 'Darwin':
        module = 'inotify'
    else:
        module = 'watchdog'
    _logger.warning("'%s' module not installed. Code autoreload feature is disabled", module)
    return None
