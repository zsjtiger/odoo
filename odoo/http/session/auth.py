# Part of Odoo. See LICENSE file for full copyright and licensing details.
"""The operations on the sessions: the authentication, the logout, the rotation and the devices."""

from __future__ import annotations
import contextlib
import ipaddress
import logging
import secrets
import time
import typing
from contextlib import suppress
from datetime import datetime
from zlib import adler32
from odoo.api import Environment
from odoo.tools import consteq, get_lang
from odoo.http import request
from odoo.http.geoip import GeoIP

if typing.TYPE_CHECKING:

    from odoo.http.requestlib import Request

from .session import DEFAULT_LANG, DEVICE_ACTIVITY_UPDATE_FREQUENCY, Device, Session, SessionExpiredException
from .store import session_store

_logger = logging.getLogger('odoo.http')


def get_default_session() -> dict:
    """ The dictionary to initialise a new session with. """
    return {
        'context': {
            # the following keys must be set at runtime:
            # 'lang': request.default_lang(),
            # 'host_id': env['ir.http']._get_host_id_from_domain(request.httprequest.host),
        },
        'create_time': time.time(),
        'db': None,
        'debug': '',
        'login': None,
        'uid': None,
        'session_token': None,
        '_devices': {},
        '_device_salt': secrets.token_urlsafe(),
    }


def authenticate(session: Session, env: Environment, credential: dict) -> dict:
    """
    Authenticate the current user with the given db, login and
    credential. If successful, store the authentication parameters in
    the current session, unless multi-factor-auth (MFA) is
    activated. In that case, that last part will be done by
    :ref:`finalize`.

    .. versionchanged:: saas-15.3
        The current request is no longer updated using the user and
        context of the session when the authentication is done using
        a database different than request.db. It is up to the caller
        to open a new cursor/registry/env on the given database.
    """
    wsgienv = {
        'interactive': True,
        'base_location': request.httprequest.url_root.rstrip('/'),
        'HTTP_HOST': request.httprequest.environ['HTTP_HOST'],
        'REMOTE_ADDR': request.httprequest.environ['REMOTE_ADDR'],
    }
    env = env(user=None, su=False)
    auth_info = env['res.users'].authenticate(credential, wsgienv)
    pre_uid = auth_info['uid']

    session.uid = None
    session['pre_login'] = credential['login']
    session['pre_uid'] = pre_uid

    # if 2FA is disabled we finalize immediately
    user = env['res.users'].browse(pre_uid)
    if auth_info.get('mfa') == 'skip' or not user._mfa_url():
        finalize(session, env)

    if request and request.session is session and request.db == env.registry.db_name:
        request.env = env(user=session.uid, context=session.context)
        request.update_context(lang=get_lang(request.env(user=pre_uid)).code)

    return auth_info


def finalize(session: Session, env: Environment) -> None:
    """
    Finalizes a partial session, should be called on MFA validation
    to convert a partial / pre-session into a logged-in one.
    """
    login = session.pop('pre_login')
    uid = session.pop('pre_uid')

    env = env(user=uid)
    user_context = dict(env['res.users'].context_get())

    session.should_rotate = True
    session.update({
        'db': env.registry.db_name,
        'login': login,
        'uid': uid,
        'context': user_context,
        'session_token': env.user._compute_session_token(session.sid),
    })
    env.user._after_session_login()


def logout(session: Session, *, keep_db: bool = False) -> None:
    db = session.db if keep_db else get_default_session()['db']  # None
    debug = session.debug
    session.clear()
    session.update(get_default_session(), db=db, debug=debug)
    session.context['lang'] = request.default_lang() if request else DEFAULT_LANG
    session.should_rotate = True

    if request and request.env:
        request.env['ir.http']._post_logout()


def touch(session: Session):
    session.is_dirty = True


def collapse_ip_address(ip_address: str) -> str:
    # IPv6 unicast and anycast addresses are commonly structured with a 64-bit
    # network prefix and a 64-bit interface identifier. The interface identifier
    # is designed to identify a network interface and may change over time (for
    # example, due to privacy extensions). Using the /64 prefix for device
    # identification avoids treating the same network endpoint as multiple
    # devices when only the interface identifier changes.
    # The downside is that it is no longer possible to tell apart different
    # hosts in a same network (e.g. multiple coworkers in a same building).
    with contextlib.suppress(ipaddress.AddressValueError):
        return str(ipaddress.IPv6Network(f'{ip_address}/64', strict=False))
    return ip_address


def get_device(session: Session, request: Request) -> Device:
    """
    :return: dict that corresponds to the current device
    """
    # TODO (v20): remove backward compatibility
    if '_devices' not in session:
        session['_devices'] = {}
        session.is_dirty = True

    ip_address = request.httprequest.remote_addr
    ip_address_key = collapse_ip_address(ip_address)
    user_agent = request.httprequest.user_agent.string
    # No collision with different IP addresses
    device_key = f'{ip_address_key.encode().hex()}{adler32(user_agent.encode()):x}'

    with suppress(KeyError):
        return session['_devices'][device_key]

    geoip = GeoIP(ip_address)

    session['_devices'][device_key] = new_device = {
        'ip_address': ip_address_key,
        'user_agent': user_agent,
        'first_activity': int(datetime.now().timestamp()),
        'last_activity': None,
        'country': geoip.country.name,
        'city': geoip.city.name,
        'trusted': not session['_devices'],  # First device in a session is always trusted
    }
    session.is_dirty = True
    return new_device


def update_device(session: Session, request: Request) -> Device | None:
    """
    :return: dict if the current device has been updated, ``None`` otherwise
    """
    if session.get('_trace_disable'):
        # To avoid generating useless logs, e.g. for automated technical sessions,
        # a session can be flagged with `_trace_disable`. This should never be done
        # without a proper assessment of the consequences for auditability.
        # Non-admin users have no direct or indirect way to set this flag, so it can't
        # be abused by unprivileged users. Such sessions will of course still be
        # subject to all other auditing mechanisms (server logs, web proxy logs,
        # metadata tracking on modified records, etc.)
        return None

    device = get_device(session, request)

    now = int(datetime.now().timestamp())
    if device['last_activity'] \
        and (now - device['last_activity']) < DEVICE_ACTIVITY_UPDATE_FREQUENCY:
        return None

    device['last_activity'] = now
    session.is_dirty = True
    return device


def update_device_fingerprint(session: Session, request: Request, fingerprint: str) -> bool:
    """
    :return: ``True`` if the current device is trusted, ``False`` otherwise
    """
    device = get_device(session, request)
    if device.get('trusted'):
        session['_device_fingerprint'] = fingerprint
    elif consteq(session.setdefault('_device_fingerprint', fingerprint), fingerprint):
        device['trusted'] = True
        session.is_dirty = True
    else:
        _logger.warning("Untrusted device for session %s (uid=%s): %s %s",
            session.sid[:8], session.uid, device['ip_address'], device['user_agent'])
        device['trusted'] = False
        session.is_dirty = True
    return device['trusted']


def check(session: Session, request_or_env: Request | Environment) -> None:
    """
    Verify that the session is not expired, and that the token saved
    in the session matches the session token computed for the user.

    The session token changes when some sensitive informations about
    the user changed: active, login, password, ...

    On success, it logs the request in the ``res.device.log`` and
    returns.

    On failure, it logs the session out (but keep the database) and
    raises a :class:`SessionExpiredException` with an appropriate
    message. See also :meth:`logout`.

    :raises SessionExpiredException: when the session is expired.
    """
    if isinstance(request_or_env, Environment):
        request, env = None, request_or_env
    else:
        request, env = request_or_env, request_or_env.env
    del request_or_env
    session_store().delete_old_sessions(session)
    # Make sure we don't use a deleted session that can be saved again
    if session.get('deletion_time', float('+inf')) <= time.time():
        logout(session, keep_db=True)
        e = "session is too old"
        raise SessionExpiredException(e)
    user = env['res.users'].browse(session['uid'])
    expected = user._compute_session_token(session.sid)
    if expected:
        # TODO: use secrets.compare_digest
        if consteq(expected, session['session_token']):
            if request:
                env['res.device.log']._update_device(request)
            return
        # If the session token is not valid, we check if the legacy
        # version works and convert the session token to the new one
        legacy_expected = user._legacy_session_token_hash_compute(session.sid)
        if legacy_expected and consteq(legacy_expected, session['session_token']):
            session['session_token'] = expected
            if request:
                env['res.device.log']._update_device(request)
            return
    logout(session, keep_db=True)
    e = "session token mismatch; likely because the user credentials changed"
    raise SessionExpiredException(e)
