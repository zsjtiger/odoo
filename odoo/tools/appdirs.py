# Part of Odoo. See LICENSE file for full copyright and licensing details.
"""Locate the user and system directories of the application (Linux and macOS).

Linux follows the XDG Base Directory specification, macOS the ``~/Library``
and ``/Library`` layout.
"""
import os
import sys


def _with_appname(path, appname):
    return os.path.join(path, appname) if appname else path


def user_data_dir(appname=None, appauthor=None):
    if sys.platform == 'darwin':
        path = os.path.expanduser('~/Library/Application Support')
    else:
        path = os.getenv('XDG_DATA_HOME', os.path.expanduser('~/.local/share'))
    return _with_appname(path, appname)


def site_data_dir(appname=None, appauthor=None):
    if sys.platform == 'darwin':
        path = '/Library/Application Support'
    else:
        path = os.getenv('XDG_DATA_DIRS', '/usr/local/share:/usr/share').split(os.pathsep)[0]
    return _with_appname(path, appname)


def user_config_dir(appname=None, appauthor=None):
    if sys.platform == 'darwin':
        return user_data_dir(appname, appauthor)
    path = os.getenv('XDG_CONFIG_HOME', os.path.expanduser('~/.config'))
    return _with_appname(path, appname)


def site_config_dir(appname=None, appauthor=None):
    if sys.platform == 'darwin':
        return site_data_dir(appname, appauthor)
    path = os.getenv('XDG_CONFIG_DIRS', '/etc/xdg').split(os.pathsep)[0]
    return _with_appname(path, appname)
