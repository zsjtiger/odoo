# Part of Odoo. See LICENSE file for full copyright and licensing details.
"""The configuration manager: the options of the server, their parsing and their values."""

import collections
import errno
import functools
import logging
import os
import warnings
from os.path import abspath, expanduser, expandvars, normcase, realpath
from odoo import release


from . import checks as cfg_checks, cli as cfg_cli, files as cfg_files, postprocess as cfg_postprocess
from .options import DEFAULT_COLOR_SPEC, EMPTY, _dangerous_logger, crypt_context


class configmanager:
    def __init__(self):
        self._default_options = {}
        self._file_options = {}
        self._env_options = {}
        self._cli_options = {}
        self._runtime_options = {}
        self.options = collections.ChainMap(
            self._runtime_options,
            self._cli_options,
            self._env_options,
            self._file_options,
            self._default_options,
        )

        # dictionary mapping option destination (keys in self.options) to OdooOptions.
        self.options_index = {}

        # list of nargs='?' options, indexed by short/long option (-x, --xx)
        self.optional_options = {}

        # optional [colors] options, no color until we load_color_options()
        self.colors: dict[str, bool] = dict.fromkeys(DEFAULT_COLOR_SPEC, False)

        # map old name -> new name
        self.aliases = {
            "import_image_maxbytes": "import_file_maxbytes",
            "import_image_regex": "import_url_regex",
            "import_image_timeout": "import_file_timeout",
        }

        self.parser = self._build_cli()
        self._load_default_options()
        self._parse_config()

    def _build_cli(self):
        return cfg_cli._build_cli(self)

    def _load_default_options(self):
        return cfg_cli._load_default_options(self)

    _log_entries = []   # helpers for log() and warn(), accumulate messages
    _warn_entries = []  # until logging is configured and the entries flushed

    @classmethod
    def _log(cls, loglevel, message, *args, **kwargs):
        # is replaced by logger.log once logging is ready
        cls._log_entries.append((loglevel, message, args, kwargs))

    @classmethod
    def _warn(cls, message, *args, **kwargs):
        # is replaced by warnings.warn once logging is ready
        cls._warn_entries.append((message, args, kwargs))

    @classmethod
    def _flush_log_and_warn_entries(cls):
        for loglevel, message, args, kwargs in cls._log_entries:
            _dangerous_logger.log(loglevel, message, *args, **kwargs)
        cls._log_entries.clear()
        cls._log = _dangerous_logger.log  # ty:ignore[invalid-assignment]

        for message, args, kwargs in cls._warn_entries:
            warnings.warn(message, *args, **kwargs, stacklevel=1)
        cls._warn_entries.clear()
        cls._warn = warnings.warn  # ty:ignore[invalid-assignment]

    def parse_config(self, args: list[str] | None = None, *, setup_logging: bool | None = None) -> None:
        """ Parse the configuration file (if any) and the command-line
        arguments.

        This method initializes odoo.tools.config and openerp.conf (the
        former should be removed in the future) with library-wide
        configuration values.

        This method must be called before proper usage of this library can be
        made.

        Typical usage of this method:

            odoo.tools.config.parse_config(sys.argv[1:])
        """
        from odoo import modules  # noqa: PLC0415
        from odoo.core.logging import init_logger  # noqa: PLC0415
        opt = self._parse_config(args)
        if setup_logging is not False:
            init_logger()
            self.load_color_options()
            # warn after having done setup, so it has a chance to show up
            # (mostly once this warning is bumped to DeprecationWarning proper)
            if setup_logging is None:
                warnings.warn(
                    "As of Odoo 20, it is strongly recommended to specify"
                    " whether you want Odoo to setup its own logging (or want"
                    " to handle it yourself)",
                    category=DeprecationWarning,
                    stacklevel=2,
                )
        self._warn_deprecated_options()
        self._flush_log_and_warn_entries()
        modules.module.initialize_sys_path()
        return opt

    def _parse_config(self, args=()):
        # preprocess the args to add support for nargs='?'
        for arg_no, arg in enumerate(args or ()):
            if option := self.optional_options.get(arg):
                if arg_no == len(args) - 1 or args[arg_no + 1].startswith('-'):
                    args[arg_no] += '=' + self.format(option.dest, option.const)
                    self._log(logging.DEBUG, "changed %s for %s", arg, args[arg_no])

        opt, unknown_args = self.parser.parse_args(args or [])
        if unknown_args:
            self.parser.error(f"unrecognized parameters: {' '.join(unknown_args)}")

        if not opt.save and opt.config and not os.access(opt.config, os.R_OK):
            self.parser.error(f"the config file {opt.config!r} selected with -c/--config doesn't exist or is not readable, use --save if you want to generate it")

        # Even if they are not exposed on the CLI, cli un-loadable variables still show up in the opt, remove them
        for option_name in list(vars(opt).keys()):
            if not self.options_index[option_name].cli_loadable:
                delattr(opt, option_name)  # hence list(...) above

        self._load_env_options()
        self._load_cli_options(opt)
        self._load_file_options(self['config'])
        self._postprocess_options()

        if opt.save:
            self.save()

        return opt

    def _load_env_options(self):
        self._env_options.clear()
        environ = os.environ
        for option_name, option in self.options_index.items():
            env_name = option.env_name
            if env_name and env_name in environ:
                self._env_options[option_name] = self.parse(option_name, environ[env_name])
        if environ.get('OPENERP_SERVER'):
            self._warn("Since ages ago, the OPENERP_SERVER environment variable has been replaced by ODOO_RC", DeprecationWarning)

    def _load_cli_options(self, opt):
        # odoo.cli.main.main parses the config twice, the second time
        # without --addons-path but expect the value to be persisted
        addons_path = self._cli_options.pop('addons_path', None)
        self._cli_options.clear()
        if addons_path is not None:
            self._cli_options['addons_path'] = addons_path

        keys = [
            option_name for option_name, option
            in self.options_index.items()
            if option.cli_loadable
            if option.action != 'append'
        ]

        for arg in keys:
            if getattr(opt, arg, None) is not None:
                self._cli_options[arg] = getattr(opt, arg)

        if opt.log_handler:
            self._cli_options['log_handler'] = [handler for comma in opt.log_handler for handler in comma]

    def load_color_options(self):
        return cfg_postprocess.load_color_options(self)

    def _postprocess_options(self):
        return cfg_postprocess._postprocess_options(self)

    def _warn_deprecated_options(self):
        return cfg_postprocess._warn_deprecated_options(self)

    @classmethod
    @classmethod
    def _is_addons_path(cls, path):
        return cfg_checks._is_addons_path(cls, path)

    @classmethod
    @classmethod
    def _check_addons_path(cls, option, opt, value):
        return cfg_checks._check_addons_path(cls, option, opt, value)

    @classmethod
    @classmethod
    def _check_upgrade_path(cls, option, opt, value):
        return cfg_checks._check_upgrade_path(cls, option, opt, value)

    @classmethod
    @classmethod
    def _check_scripts(cls, option, opt, value):
        return cfg_checks._check_scripts(cls, option, opt, value)

    @classmethod
    @classmethod
    def _is_upgrades_path(cls, path):
        return cfg_checks._is_upgrades_path(cls, path)

    @classmethod
    @classmethod
    def _check_bool(cls, option, opt, value):
        return cfg_checks._check_bool(cls, option, opt, value)

    @classmethod
    @classmethod
    def _check_comma(cls, option_name, option, value):
        return cfg_checks._check_comma(cls, option_name, option, value)

    @classmethod
    @classmethod
    def _check_path(cls, option, opt, value):
        return cfg_checks._check_path(cls, option, opt, value)

    @classmethod
    @classmethod
    def _check_without_demo(cls, option, opt, value):
        # invert the result because it is stored in "with_demo"
        return cfg_checks._check_without_demo(cls, option, opt, value)

    def parse(self, option_name, value):
        if not isinstance(value, str):
            e = f"can only cast strings: {value!r}"
            raise TypeError(e)
        if value == 'None':
            return None
        option = self.options_index[option_name]
        if option.action in ('store_true', 'store_false'):
            check_func = self._check_bool
        else:
            check_func = self.parser.option_class.TYPE_CHECKER[option.type]
        return check_func(option, option_name, value)

    @classmethod
    @classmethod
    def _format_string(cls, value):
        return cfg_checks._format_string(cls, value)

    @classmethod
    @classmethod
    def _format_list(cls, value):
        return cfg_checks._format_list(cls, value)

    @classmethod
    @classmethod
    def _format_without_demo(cls, value):
        return cfg_checks._format_without_demo(cls, value)

    def format(self, option_name, value):
        return cfg_checks.format_config(self, option_name, value)

    def _load_file_options(self, rcfile):
        return cfg_files._load_file_options(self, rcfile)

    def save(self, keys=None):
        return cfg_files.save(self, keys)

    def get(self, key, default=None):
        return self.options.get(key, default)

    def __setitem__(self, key, value):
        if isinstance(value, str) and key in self.options_index:
            value = self.parse(key, value)
        self.options[key] = value

    def __getitem__(self, key):
        return self.options[key]

    @functools.cached_property
    def root_path(self):
        return self._normalize(os.path.join(os.path.dirname(__file__), '..', '..'))

    @property
    def addons_base_dir(self):
        return os.path.join(self.root_path, 'addons')

    @property
    def addons_community_dir(self):
        return os.path.join(os.path.dirname(self.root_path), 'addons')

    @property
    def addons_data_dir(self):
        add_dir = os.path.join(self['data_dir'], 'addons')
        d = os.path.join(add_dir, release.series)
        if not os.path.exists(d):
            try:
                # bootstrap parent dir +rwx
                if not os.path.exists(add_dir):
                    os.makedirs(add_dir, 0o700)
                # try to make +rx placeholder dir, will need manual +w to activate it
                os.makedirs(d, 0o500)
            except OSError:
                self._log(logging.DEBUG, 'Failed to create addons data dir %s', d)
        return d

    @property
    def session_dir(self):
        d = os.path.join(self['data_dir'], 'sessions')
        try:
            os.makedirs(d, 0o700)
        except OSError as e:
            if e.errno != errno.EEXIST:
                raise
            assert os.access(d, os.W_OK), \
                "%s: directory is not writable" % d
        return d

    def filestore(self, dbname):
        return os.path.join(self['data_dir'], 'filestore', dbname)

    def set_admin_password(self, new_password):
        self.options['admin_passwd'] = crypt_context.hash(new_password)

    def verify_admin_password(self, password):
        """Verifies the super-admin password, possibly updating the stored hash if needed"""
        stored_hash = self.options['admin_passwd']
        if not stored_hash:
            # empty password/hash => authentication forbidden
            return False
        result, updated_hash = crypt_context.verify_and_update(password, stored_hash)
        if result:
            if updated_hash:
                self.options['admin_passwd'] = updated_hash
            return True
        return False

    @property
    def http_socket_activation(self):
        return (
            self['http_enable']
            and os.getenv('LISTEN_FDS') == '1'
            and os.getenv('LISTEN_PID') == str(os.getpid())
        )

    @property
    def max_http_threads(self):
        mht = os.getenv('ODOO_MAX_HTTP_THREADS', str(2 * os.cpu_count() + 1))
        if not (mht.isdecimal() and mht.isascii()):
            e = f"ODOO_MAX_HTTP_THREADS={mht} but it is not a positive integer"
            raise ValueError(e)
        return int(mht)

    @classmethod
    def _normalize(cls, path):
        if not path:
            return ''
        return normcase(realpath(abspath(expanduser(expandvars(path.strip())))))

    def _get_sources(self, name):
        """Extract the option from the many sources"""
        return {
            **{
                f'source#{no}': source.get(name, EMPTY)
                for no, source in enumerate(self.options.maps[:-4])
            },
            'runtime': self._runtime_options.get(name, EMPTY),
            'command line': self._cli_options.get(name, EMPTY),
            'environment variable': self._env_options.get(name, EMPTY),
            'configuration file': self._file_options.get(name, EMPTY),
            'hardcoded default': self._default_options.get(name, EMPTY),
        }


config = configmanager()
