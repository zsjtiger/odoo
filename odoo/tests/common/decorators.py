# Part of Odoo. See LICENSE file for full copyright and licensing details.
"""Decorators that tag, skip and parametrize the tests."""

from __future__ import annotations

import contextlib
import typing
from collections import defaultdict
from functools import wraps

if typing.TYPE_CHECKING:
    pass

from .utils import _logger

standalone_tests = defaultdict(list)


def standalone(*tags):
    """ Decorator for standalone test functions.  This is somewhat dedicated to
    tests that install, upgrade or uninstall some modules, which is currently
    forbidden in regular test cases.  The function is registered under the given
    ``tags`` and the corresponding Odoo module name.
    """
    def register(func):
        # register func by odoo module name
        if func.__module__.startswith('odoo.addons.'):
            module = func.__module__.split('.')[2]
            standalone_tests[module].append(func)
        # register func with aribitrary name, if any
        for tag in tags:
            standalone_tests[tag].append(func)
        standalone_tests['all'].append(func)
        return func

    return register


def no_retry(arg):
    """Disable auto retry on decorated test method or test class"""
    arg._retry = False
    return arg


def users(*logins):
    """ Decorate a method to execute it once for each given user. """
    assert logins, "Expecting at least one login to execute"

    def users_decorator(func, /):
        @wraps(func)
        def with_users(self, *args, **kwargs):
            old_uid = self.uid
            try:
                # retrieve users
                Users = self.env['res.users'].with_context(active_test=False)
                user_id = {
                    user.login: user.id
                    for user in Users.search_fetch(
                        [('login', 'in', list(logins))],
                        ['login'], order='login',
                    )
                }
                for login in logins:
                    with self.subTest(login=login):
                        # switch user and execute func
                        self.uid = user_id[login]
                        func(self, *args, **kwargs)
                        self.env.flush_all()
                    # Invalidate the cache between subtests, in order to not reuse
                    # the former user's cache (`test_read_mail`, `test_write_mail`)
                    self.env.invalidate_all()
            finally:
                self.uid = old_uid

        return with_users
    return users_decorator


def warmup(func, /):
    """
    Stabilize assertQueries and assertQueryCount assertions.

    Reset the cache to a stable state by flushing pending changes and
    invalidating the cache.

    Warmup the ormcaches by running the decorated function an extra time
    before the actual test runs. The extra execution ignores
    assertQueries and assertQueryCount assertions, it also discardes all
    changes but the ormcaches ones.
    """
    @wraps(func)
    def warmup(self, *args, **kwargs):
        self.env.flush_all()
        self.env.invalidate_all()
        # run once to warm up the caches
        self.warm = False
        with contextlib.closing(self.cr.savepoint(flush=False)):
            func(self, *args, **kwargs)
            self.env.flush_all()
        # run once for real
        self.env.invalidate_all()
        self.warm = True
        func(self, *args, **kwargs)
    return warmup


def tagged(*tags):
    """A decorator to tag BaseCase objects.

    Tags are stored in a set that can be accessed from a 'test_tags' attribute.

    A tag prefixed by '-' will remove the tag e.g. to remove the 'standard' tag.

    By default, all Test classes from odoo.tests.common have a test_tags
    attribute that defaults to 'standard' and 'post_install'.

    When using class inheritance, the tags ARE inherited.
    """
    include = {t for t in tags if not t.startswith('-')}
    exclude = {t[1:] for t in tags if t.startswith('-')}

    def tags_decorator(obj):
        obj.test_tags = (getattr(obj, 'test_tags', set()) | include) - exclude
        at_install = 'at_install' in obj.test_tags
        post_install = 'post_install' in obj.test_tags
        if not (at_install ^ post_install):
            _logger.warning('A tests should be either at_install or post_install, which is not the case of %r', obj)
        return obj
    return tags_decorator
