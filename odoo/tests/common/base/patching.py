"""The patching of the test cases: the mocks, the contexts of the users and of the debug mode, and the profiling."""

from __future__ import annotations

import typing
from contextlib import contextmanager
from unittest.mock import Mock, patch as _unittest_patch
from odoo.http import request_var
from odoo.http.session import (
    get_default_session,
)
from odoo.tools import DotDict
from odoo.tools.profiling import profiler

if typing.TYPE_CHECKING:
    pass


def patch(self, obj, key, val):
    """ Do the patch ``setattr(obj, key, val)``, and prepare cleanup. """
    patcher = _unittest_patch.object(obj, key, val)   # this is unittest.mock.patch
    patcher.start()
    self.addCleanup(patcher.stop)


def classPatch(cls, obj, key, val):
    """ Do the patch ``setattr(obj, key, val)``, and prepare cleanup. """
    patcher = _unittest_patch.object(obj, key, val)   # this is unittest.mock.patch
    patcher.start()
    cls.addClassCleanup(patcher.stop)


def startPatcher(self, patcher):
    mock = patcher.start()
    self.addCleanup(patcher.stop)
    return mock


def startClassPatcher(cls, patcher):
    mock = patcher.start()
    cls.addClassCleanup(patcher.stop)
    return mock


def enterContext(self, cm):
    """Enters the supplied context manager.

    If successful, also adds its __exit__ method as a cleanup
    function and returns the result of the __enter__ method.
    """
    return _enter_context(cm, self.addCleanup)


def enterClassContext(cls, cm):
    """Same as enterContext, but class-wide."""
    return _enter_context(cm, cls.addClassCleanup)


@contextmanager
def with_user(self, login):
    """ Change user for a given test, like with self.with_user() ... """
    old_uid = self.uid
    old_env = self.env
    try:
        user = self.env['res.users'].sudo().search([('login', '=', login)], order='login')
        assert user, "Login %s not found" % login
        # switch user
        self.uid = user.id
        self.env = self.env(user=self.uid)
        yield
    finally:
        # back
        self.uid = old_uid
        self.env = old_env


@contextmanager
def debug_mode(self):
    """ Enable the effects of debug mode (in particular for group ``base.group_no_one``). """
    request = Mock(
        httprequest=Mock(host='localhost'),
        db=self.env.cr.dbname,
        env=self.env,
        session=DotDict(get_default_session(), debug='1', sid=''),
    )
    reset_req = None
    try:
        self.env.flush_all()
        self.env.invalidate_all()
        reset_req = request_var.set(request)
        yield
        self.env.flush_all()
        self.env.invalidate_all()
    finally:
        current_request = request_var.get()
        if reset_req is not None:
            request_var.reset(reset_req)
        if current_request is not request:
            raise Exception('Wrong request stack cleanup.')


def profile(self, description='', **kwargs):
    test_method = getattr(self, '_testMethodName', 'Unknown test method')
    if not hasattr(self, 'profile_session'):
        self.profile_session = profiler.make_session(test_method)
    if 'db' not in kwargs:
        kwargs['db'] = self.env.cr.dbname
    return profiler.Profiler(
        description='%s uid:%s %s %s' % (test_method, self.env.user.id, 'warm' if self.warm else 'cold', description),
        profile_session=self.profile_session,
        **kwargs)


def _enter_context(cm, addcleanup):
    # We look up the special methods on the type to match the with
    # statement.
    cls = type(cm)
    try:
        enter = cls.__enter__
        exit = cls.__exit__
    except AttributeError:
        raise TypeError(f"'{cls.__module__}.{cls.__qualname__}' object does "
                        f"not support the context manager protocol") from None
    result = enter(cm)
    addcleanup(exit, cm, None, None, None)
    return result
