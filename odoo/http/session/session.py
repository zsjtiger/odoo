# Part of Odoo. See LICENSE file for full copyright and licensing details.
"""The session objects: the session and the device of a visitor, the constants of the sessions and their token and lifetime."""

from __future__ import annotations
import json
import logging
import re
import typing
from collections.abc import MutableMapping
from http import HTTPStatus
from odoo.api import Environment

if typing.TYPE_CHECKING:

    pass


_logger = logging.getLogger('odoo.http')


DEFAULT_LANG = 'en_US'


SESSION_LIFETIME = 60 * 60 * 24 * 7  # 1 week


SESSION_ROTATION_EXCLUDED_PATHS = (
    '/websocket/on_closed',
    '/websocket/peek_notifications',
    '/websocket/update_bus_presence',
)  # Naughty list, don't add more routes in it.


SESSION_ROTATION_INTERVAL = 60 * 60 * 3  # 3 hours


SESSION_ROTATION_INTERVAL_HEADER_SKIP = "X-Odoo-Skip-Session-Rotation-Interval"


SESSION_DELETION_TIMER = 120


STORED_SESSION_BYTES = 42


DEVICE_ACTIVITY_UPDATE_FREQUENCY = 3600  # 1 hour


_base64_urlsafe_re = re.compile(r'^[A-Za-z0-9_-]{84,86}$')


_session_identifier_re = re.compile(r'^[A-Za-z0-9_-]{42}$')


class SessionExpiredException(Exception):
    http_status = HTTPStatus.FORBIDDEN


class CheckIdentityException(SessionExpiredException):
    """ Exception raised when a user is requested to re-authenticate. """
    loglevel = logging.DEBUG


class Session(MutableMapping):
    """ Structure containing data persisted across requests. """
    __slots__ = (
        '_Session__data',
        'can_save',
        'is_dirty',
        'is_new',
        'should_rotate',
        'sid',
    )

    def __init__(self, data, sid, /, new: bool = False):
        self.can_save: bool = True
        self.__data = {}
        self.update(data)
        self.is_dirty: bool = False
        self.is_new = new
        self.should_rotate: bool = False
        self.sid = sid

    def __getitem__(self, item):
        return self.__data[item]

    def __setitem__(self, item, value):
        value = json.loads(json.dumps(value))
        if item not in self.__data or self.__data[item] != value:
            self.is_dirty = True
        self.__data[item] = value

    def __delitem__(self, item):
        del self.__data[item]
        self.is_dirty = True

    def __len__(self):
        return len(self.__data)

    def __iter__(self):
        return iter(self.__data)

    def clear(self):
        self.__data.clear()
        self.is_dirty = True

    #
    # Session properties
    #
    @property
    def uid(self):
        return self.get('uid')

    @uid.setter
    def uid(self, uid):
        self['uid'] = uid

    @property
    def db(self):
        return self.get('db')

    @db.setter
    def db(self, db):
        self['db'] = db

    @property
    def login(self):
        return self.get('login')

    @login.setter
    def login(self, login):
        self['login'] = login

    @property
    def context(self):
        return self.get('context')

    @context.setter
    def context(self, context):
        self['context'] = context

    @property
    def debug(self):
        return self.get('debug')

    @debug.setter
    def debug(self, debug):
        self['debug'] = debug

    @property
    def session_token(self):
        return self.get('session_token')

    @session_token.setter
    def session_token(self, session_token):
        self['session_token'] = session_token


class Device(typing.TypedDict):
    ip_address: str
    user_agent: str
    first_activity: int
    last_activity: int | None
    country: str
    city: str
    trusted: typing.NotRequired[bool]


def get_session_max_inactivity(env: Environment | None) -> int:
    if not env or env.cr.closed:
        return SESSION_LIFETIME

    ICP = env['ir.config_parameter'].sudo()
    return ICP.get_int('sessions.max_inactivity_seconds') or SESSION_LIFETIME


def update_session_token(session: Session, env: Environment) -> None:
    """
    Compute the session token of the current user (determined using
    ``session['uid']``) and save it in the session.

    :param env: An environment to access ``res.users``.
    """
    user = env['res.users'].browse(session['uid'])
    session['session_token'] = user._compute_session_token(session.sid)
