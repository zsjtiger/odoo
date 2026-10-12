# Part of Odoo. See LICENSE file for full copyright and licensing details.
"""Locks of the test registry: the test cursors are opened only when the lock is released."""

from __future__ import annotations

import threading
import typing
from contextlib import contextmanager
import odoo.cli
import odoo.models
import odoo.orm.models.registry
import odoo.addons.base

if typing.TYPE_CHECKING:
    pass


class RegistryRLock(threading._RLock):
    @property
    def count(self):
        return self._count  # Expose private attribute


_registry_test_lock = RegistryRLock()


_registry_test_lock.acquire()


_disable_flushing_cursor = False


@contextmanager
def release_test_lock(check_acquired=False):
    """ Releases the test lock in a context manager, the lock is acquired once the context is over."""
    if check_acquired and not _registry_test_lock.count:
        # not acquired, just noop
        yield
        return
    try:
        _registry_test_lock.release()
        yield
    finally:
        if not _registry_test_lock.acquire(timeout=60):
            tag = odoo.modules.module.current_test.canonical_tag
            exit(f'Could not re-acquire the registry lock during {tag}, exiting...')


class DummyRLock:
    """ Dummy reentrant lock, to be used while running rpc and js tests """
    def acquire(self):
        pass

    def release(self):
        pass

    def __enter__(self):
        self.acquire()

    def __exit__(self, *args):
        self.release()
