# Part of Odoo. See LICENSE file for full copyright and licensing details.
"""The store of the sessions: the storage of the files and the saving of the sessions."""

from __future__ import annotations
import functools
import glob
import json
import logging
import os
import secrets
import tempfile
import threading
import time
import typing
from contextlib import suppress
from odoo.api import Environment
from odoo.tools import config

if typing.TYPE_CHECKING:
    from collections.abc import Iterable

    from odoo.http.requestlib import Request

from .session import SESSION_DELETION_TIMER, SESSION_LIFETIME, SESSION_ROTATION_EXCLUDED_PATHS, SESSION_ROTATION_INTERVAL, SESSION_ROTATION_INTERVAL_HEADER_SKIP, STORED_SESSION_BYTES, Session, _base64_urlsafe_re, _session_identifier_re, get_session_max_inactivity, update_session_token

_logger = logging.getLogger('odoo.http')


class SessionStore:
    """ Odoo implementation of the filesystem session store. """

    def __init__(self, /, path: str | None = None, session_cls: type[Session] = Session):
        """
        :param path: the path to the folder used for storing the sessions.
            If not provided the default temporary directory is used.
        :param session_cls: The session class to use.
            Defaults to :class:`Session`.
        """
        if path is None:
            path = os.path.join(tempfile.gettempdir(), 'odoo_session_store')
            os.makedirs(path, exist_ok=True)
        self.path: str = path
        self.session_cls: type[Session] = session_cls

    def generate_key(self) -> str:
        """ Generate a 86-chars long token with 64 bytes of entropy. """
        # To be secure, random token must have at least 256 bits (32 bytes) of entropy.
        # Here we decide the use a token of 512 bits (2x32 bytes). The session (and
        # cookie) will use the full 64-bytes long token. We will also store the first 32
        # bytes in the `res.device.log` model. In case the `res.device.log` model gets
        # compromised (e.g. data breach), pirates will not be able to exploit the
        # session token because they will lack the remaining 32 bytes.
        return secrets.token_urlsafe(64)

    def is_valid_session_id(self, sid: str) -> bool:
        """ Check if a session identifier has the correct format. """
        return _base64_urlsafe_re.fullmatch(sid) is not None

    def new(self) -> Session:
        """ Generate a new session. """
        return self.session_cls({}, self.generate_key(), new=True)

    def get_session_path(self, sid: str) -> str:
        """Get complete session path."""
        # scatter sessions across 4096 (64^2) directories
        if not self.is_valid_session_id(sid):
            raise ValueError(f'Invalid session id {sid!r}')
        return os.path.join(self.path, sid[:2], sid)

    def save(self, session: Session) -> None:
        """ Save a session. """
        # Perform an atomic save
        session_path = self.get_session_path(session.sid)
        # Create session in a transaction file in the
        # root directory of file session store
        fd, tmp = tempfile.mkstemp(suffix='.__tx_sess__', dir=self.path)
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(dict(session), f)
        # Move the transaction file to the correct sub directory
        with suppress(OSError):
            try:
                os.replace(tmp, session_path)
            except FileNotFoundError:
                # Ensure directory then retry
                session_dir = os.path.dirname(session_path)
                os.mkdir(session_dir, mode=0o755)
                os.replace(tmp, session_path)
            os.chmod(session_path, 0o644)

    def delete(self, session: Session) -> None:
        """ Delete a session. """
        session_path = self.get_session_path(session.sid)
        with suppress(OSError):
            os.unlink(session_path)

    def get(self, sid: str, *, keep_sid: bool = False) -> Session:
        """
        Get a session for the sid.

        It returns a new session (with a new sid, not matter `keep_sid`)
        in case the input sid is invalid.

        It returns a new session (with a same or new sid depending on
        `keep_sid`) in case the sid is valid but that the session wasn't
        found on disk.
        """
        if not self.is_valid_session_id(sid):
            return self.new()

        try:

            with open(self.get_session_path(sid), encoding='utf-8') as f:
                try:
                    data = json.load(f)
                    return self.session_cls(data, sid, new=False)
                except ValueError:
                    _logger.debug("Could not load session data. Use empty session.", exc_info=True)
                    # The session file exists on the filesystem (the sid must be retained)
                    return self.session_cls({}, sid, new=False)

        except OSError:
            if keep_sid:
                _logger.debug("Could not load session from disk. Use empty session.", exc_info=True)
                return self.session_cls({}, sid, new=False)
            _logger.debug("Could not load session from disk. Use new session.", exc_info=True)
            return self.new()

    def rotate(self, session: Session, env: Environment, *, soft: bool = False) -> None:
        """
        Rotate the session sid.

        With a soft rotation, things like the CSRF token will still work. It's
        used for rotating the session in a way that half the bytes remain to
        identify the user and the other half to authenticate the user.

        Meanwhile with a hard rotation the entire session id is changed, which
        is useful in cases such as logging the user out.
        """
        if soft:
            # Multiple network requests can occur at the same time, all using the old session.
            # We don't want to create a new session for each request, it's better to reference the one already made.
            static = session.sid[:STORED_SESSION_BYTES]
            recent_session = self.get(session.sid)
            if 'next_sid' in recent_session:
                # A new session has already been saved on disk by a concurrent request,
                # the save_session is going to simply use session.sid to set a new cookie.
                session.sid = recent_session['next_sid']
                return
            next_sid = static + self.generate_key()[STORED_SESSION_BYTES:]
            session['next_sid'] = next_sid
            session['deletion_time'] = time.time() + SESSION_DELETION_TIMER
            self.save(session)
            # Now prepare the new session
            session['gc_previous_sessions'] = True
            session.sid = next_sid
            del session['deletion_time']
            del session['next_sid']
        else:
            self.delete(session)
            session.sid = self.generate_key()
            if hasattr(threading.current_thread(), 'sess_id'):
                _logger.info(
                    'Session rotated: %s -> %s', threading.current_thread().sess_id, session.sid[:8]
                )
            threading.current_thread().sess_id = session.sid[:8]
        if session.uid:
            assert env, "saving this session requires an environment"
            update_session_token(session, env)
        session.should_rotate = False
        session['create_time'] = time.time()
        self.save(session)

    def vacuum(self, max_lifetime=SESSION_LIFETIME):
        """ Remove expired session files older than the given lifetime. """
        threshold = time.time() - max_lifetime
        for fname in glob.iglob(os.path.join(self.path, '*', '*')):
            path = os.path.join(self.path, fname)
            with suppress(OSError):
                if os.path.getmtime(path) < threshold:
                    os.unlink(path)

    def get_missing_session_identifiers(self, identifiers: Iterable[str]) -> set[str]:
        """
        :param identifiers: session identifiers whose file existence must be checked
                            identifiers are a part session sid (first 42 chars)
        :type identifiers: iterable
        :return: the identifiers which are not present on the filesystem
        :rtype: set
        """
        # There are a lot of session files.
        # Use the param ``identifiers`` to select the necessary directories.
        # In the worst case, we have 4096 directories (64^2).
        identifiers = set(identifiers)
        directories = {
            os.path.normpath(os.path.join(self.path, identifier[:2]))
            for identifier in identifiers
        }
        # Remove the identifiers for which a file is present on the filesystem.
        for directory in directories:
            with suppress(OSError), os.scandir(directory) as session_files:
                identifiers.difference_update(sf.name[:42] for sf in session_files)
        return identifiers

    def delete_from_identifiers(self, identifiers: Iterable[str]) -> None:
        """ Delete session files matching identifiers within the session store. """
        files_to_unlink = []
        for identifier in identifiers:
            # Avoid to remove a session if it does not match an identifier.
            # This prevent malicious user to delete sessions from a different
            # database by specifying a custom ``res.device.log``.
            if not _session_identifier_re.match(identifier):
                continue
            normalized_path = os.path.normpath(os.path.join(self.path, identifier[:2], identifier + '*'))
            if normalized_path.startswith(self.path):
                files_to_unlink.extend(glob.glob(normalized_path))
        for fn in files_to_unlink:
            with suppress(OSError):
                os.unlink(fn)

    def delete_old_sessions(self, session: Session) -> None:
        """ Delete old sessions based on expiration and cleanup flag value. """
        if 'gc_previous_sessions' in session:
            if session['create_time'] + SESSION_DELETION_TIMER < time.time():
                self.delete_from_identifiers([session.sid[:STORED_SESSION_BYTES]])
                del session['gc_previous_sessions']
                self.save(session)


@functools.cache
def session_store():
    _logger.debug('HTTP sessions stored in: %s', config.session_dir)
    return SessionStore(path=config.session_dir)


def save_session(request: Request, env: Environment | None = None) -> None:
    """
    Save a modified session on disk.

    :param env: an environment to compute the session token.
        MUST be left ``None`` (in which case it uses the request's
        env) UNLESS the database changed.
    """
    sess = request.session
    if env is None:
        env = request.env

    if not sess.can_save:
        return

    if sess.should_rotate:
        session_store().rotate(sess, env)  # it saves
    elif (
        sess.uid
        and time.time() >= sess['create_time'] + SESSION_ROTATION_INTERVAL
        and request.httprequest.path not in SESSION_ROTATION_EXCLUDED_PATHS
        and not request.httprequest.headers.get(SESSION_ROTATION_INTERVAL_HEADER_SKIP)
    ):
        session_store().rotate(sess, env, soft=True)
    elif sess.is_dirty:
        session_store().save(sess)

    cookie_sid = request.cookies.get('session_id')
    if sess.is_dirty or cookie_sid != sess.sid:
        request.future_response.set_cookie(
            'session_id',
            sess.sid,
            max_age=get_session_max_inactivity(env),
            httponly=True,
        )
