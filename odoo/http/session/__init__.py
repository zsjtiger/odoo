# Part of Odoo. See LICENSE file for full copyright and licensing details.
# ruff: noqa: F401
"""HTTP sessions: the session objects, their store and the operations on them."""
from .session import CheckIdentityException, HTTPStatus, MutableMapping, re
from .store import SESSION_DELETION_TIMER, SESSION_LIFETIME, SESSION_ROTATION_EXCLUDED_PATHS, SESSION_ROTATION_INTERVAL, SESSION_ROTATION_INTERVAL_HEADER_SKIP, STORED_SESSION_BYTES, SessionStore, config, functools, get_session_max_inactivity, glob, json, os, save_session, tempfile, threading, update_session_token
from .auth import DEFAULT_LANG, DEVICE_ACTIVITY_UPDATE_FREQUENCY, Device, Environment, GeoIP, Session, SessionExpiredException, adler32, authenticate, check, collapse_ip_address, consteq, contextlib, datetime, finalize, get_default_session, get_device, get_lang, ipaddress, logging, logout, request, secrets, session_store, suppress, time, touch, typing, update_device, update_device_fingerprint

__all__ = [
    'CheckIdentityException',
    'DEFAULT_LANG',
    'DEVICE_ACTIVITY_UPDATE_FREQUENCY',
    'Device',
    'SESSION_DELETION_TIMER',
    'SESSION_LIFETIME',
    'SESSION_ROTATION_EXCLUDED_PATHS',
    'SESSION_ROTATION_INTERVAL',
    'SESSION_ROTATION_INTERVAL_HEADER_SKIP',
    'STORED_SESSION_BYTES',
    'Session',
    'SessionExpiredException',
    'SessionStore',
    'authenticate',
    'check',
    'collapse_ip_address',
    'finalize',
    'get_default_session',
    'get_device',
    'get_session_max_inactivity',
    'logout',
    'save_session',
    'session_store',
    'touch',
    'update_device',
    'update_device_fingerprint',
    'update_session_token',
]
