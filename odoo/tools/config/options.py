# Part of Odoo. See LICENSE file for full copyright and licensing details.
"""The options of the configuration: the parser of the command line and the option classes."""

import logging
import optparse
import typing
import os
from passlib.context import CryptContext
from odoo.tools.func import classproperty

if typing.TYPE_CHECKING:
    from .manager import configmanager


_dangerous_logger = logging.getLogger('odoo.tools.config')


crypt_context = CryptContext(schemes=['pbkdf2_sha512', 'plaintext'],
                             deprecated=['plaintext'],
                             pbkdf2_sha512__rounds=600_000)

  # use config._log() instead

optparse._ = str  # disable gettext  # ty:ignore[unresolved-attribute]

ALL_DEV_MODE = ['access', 'qweb', 'reload', 'xml']

DEFAULT_SERVER_WIDE_MODULES = ['base', 'rpc', 'web']

REQUIRED_SERVER_WIDE_MODULES = ['base', 'web']

DEFAULT_COLOR_SPEC = {
    'pid': 'never',
    'loglevel': 'auto',
    'session_id': 'never',
    'http_request_line': 'auto',
    'http_response_body': 'auto',
    'perf': 'auto',
    'cursor_mode': 'auto',
    'sql': 'auto',
}

class _Empty:
    def __repr__(self):
        return ''

EMPTY = _Empty()  # noqa: E305

class OdooOptionParser(optparse.OptionParser):
    def _match_long_opt(self, opt):
        # --st is an "ambigous" prefix for --stop and --stop-after-init
        # which actually are the same option, make it return that single
        # option.
        possibilities = [
            (long_opt, option)
            for long_opt, option
            in self._long_opt.items()
            if long_opt.startswith(opt)
        ]
        if len({p[1] for p in possibilities}) == 1:
            return possibilities[0][0]
        return super()._match_long_opt(opt)

class _OdooOption(optparse.Option):
    config: "configmanager"

    TYPES = ['int', 'float', 'string', 'choice', 'bool', 'path', 'comma',
             'addons_path', 'upgrade_path', 'pre_upgrade_scripts', 'without_demo']

    @classproperty
    def TYPE_CHECKER(cls):
        return {
            'int': lambda _option, _opt, value: int(value),
            'float': lambda _option, _opt, value: float(value),
            'string': lambda _option, _opt, value: str(value),
            'choice': optparse.check_choice,
            'bool': cls.config._check_bool,
            'path': cls.config._check_path,
            'comma': cls.config._check_comma,
            'addons_path': cls.config._check_addons_path,
            'upgrade_path': cls.config._check_upgrade_path,
            'pre_upgrade_scripts': cls.config._check_scripts,
            'without_demo': cls.config._check_without_demo,
        }

    @classproperty
    def TYPE_FORMATTER(cls):
        return {
            'int': cls.config._format_string,
            'float': cls.config._format_string,
            'string': cls.config._format_string,
            'choice': cls.config._format_string,
            'bool': cls.config._format_string,
            'path': cls.config._format_string,
            'comma': cls.config._format_list,
            'addons_path': cls.config._format_list,
            'upgrade_path': cls.config._format_list,
            'pre_upgrade_scripts': cls.config._format_list,
            'without_demo': cls.config._format_without_demo,
        }

    def __init__(self, *opts, **attrs):
        self.my_default = attrs.pop('my_default', None)
        self.cli_loadable = attrs.pop('cli_loadable', True)
        env_name = attrs.pop('env_name', None)
        self.env_name = env_name or ''
        self.file_loadable = attrs.pop('file_loadable', True)
        self.file_exportable = attrs.pop('file_exportable', self.file_loadable)
        self.nargs_ = attrs.get('nargs')
        if self.nargs_ == '?':
            const = attrs.pop('const', None)
            attrs['nargs'] = 1
        attrs.setdefault('metavar', attrs.get('type', 'string').upper())
        super().__init__(*opts, **attrs)
        if 'default' in attrs:
            self.config._log(logging.WARNING, "please use my_default= instead of default= with option %s", self)
        if self.file_exportable and not self.file_loadable:
            e = (f"it makes no sense that the option {self} can be exported "
                  "to the config file but not loaded from the config file")
            raise ValueError(e)
        is_new_option = False
        if self.dest and self.dest not in self.config.options_index:
            self.config.options_index[self.dest] = self
            is_new_option = True
        if self.nargs_ == '?':
            self.const = const
            for opt in self._short_opts + self._long_opts:
                self.config.optional_options[opt] = self
        if env_name is None and is_new_option and self.file_loadable and self.dest:
            # generate an env_name for file_loadable settings that are in the index
            self.env_name = 'ODOO_' + self.dest.upper()
        elif env_name and not is_new_option:
            raise ValueError(f"cannot set env_name to an option that is not indexed: {self}")

    def __str__(self):
        out = []
        if self.cli_loadable:
            out.append(super().__str__())  # e.g. -i/--init
        if self.file_loadable:
            out.append(self.dest)
        return '/'.join(out)

class _FileOnlyOption(_OdooOption):
    def __init__(self, **attrs):
        super().__init__(**attrs, cli_loadable=False, help=optparse.SUPPRESS_HELP)

    def _check_opt_strings(self, opts):
        if opts:
            e = "No option can be supplied"
            raise TypeError(e)

    def _set_opt_strings(self, opts):
        return

class _PosixOnlyOption(_OdooOption):
    def __init__(self, *opts, **attrs):
        if os.name != 'posix':
            attrs['help'] = optparse.SUPPRESS_HELP
            attrs['cli_loadable'] = False
            attrs['env_name'] = ''
            attrs['file_loadable'] = False
            attrs['file_exportable'] = False
        super().__init__(*opts, **attrs)

def _deduplicate_loggers(loggers):
    """ Avoid saving multiple logging levels for the same loggers to a save
    file, that just takes space and the list can potentially grow unbounded
    if for some odd reason people use :option`--save`` all the time.
    """
    # dict(iterable) -> the last item of iterable for any given key wins,
    # which is what we want and expect. Output order should not matter as
    # there are no duplicates within the output sequence
    return (
        f'{logger}:{level}'
        for logger, level in dict(it.split(':') for it in loggers).items()
    )
