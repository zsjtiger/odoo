# Part of Odoo. See LICENSE file for full copyright and licensing details.
"""The post-processing of the options: the colors, the deprecated options and the derived values."""

import configparser as ConfigParser
import logging
import optparse
import os


from .options import ALL_DEV_MODE, DEFAULT_COLOR_SPEC, DEFAULT_SERVER_WIDE_MODULES, EMPTY, REQUIRED_SERVER_WIDE_MODULES, _deduplicate_loggers


def load_color_options(self):
    if os.getenv('NO_COLOR'):
        self.colors = dict.fromkeys(DEFAULT_COLOR_SPEC, False)
        return

    if os.getenv('FORCE_COLOR'):
        self.colors = dict.fromkeys(DEFAULT_COLOR_SPEC, True)
        return

    color2bool = {'always': True, 'never': False, 'auto': any(
        isinstance(handler, logging.StreamHandler)
        and hasattr(handler.stream, 'fileno')
        and os.isatty(handler.stream.fileno())
        for handler in logging.getLogger().handlers
    )}

    if color := os.getenv('ODOO_PY_COLORS'):
        try:
            value = color2bool[color]
        except KeyError:
            try:
                value = self._check_bool(..., ..., color)  # backward compat
            except optparse.OptionValueError:
                e = f"environ['ODOO_PY_COLORS'] is not always/never/auto: {color!r}"
                raise optparse.OptionValueError(e) from None

        self.colors = dict.fromkeys(DEFAULT_COLOR_SPEC, value)
        return

    self.colors = {
        name: color2bool[value]
        for name, value in DEFAULT_COLOR_SPEC.items()
    }

    p = ConfigParser.RawConfigParser()
    try:
        p.read([self['config']])
        file_options = p.items('colors')
    except (OSError, ConfigParser.NoSectionError):
        pass
    else:
        for name, value in file_options:
            if name not in DEFAULT_COLOR_SPEC:
                self._log(logging.WARNING, "unknown color option: %r, skipped", name)
                continue
            try:
                self.colors[name] = color2bool[value]
            except KeyError:
                e = f"color option {name}: invalid value: {value!r}"
                raise optparse.OptionValueError(e) from None


def _postprocess_options(self):
    self._runtime_options.clear()

    # check for mutualy exclusive / dependant options
    if self.options['syslog'] and self.options['logfile']:
        self.parser.error("the syslog and logfile options are exclusive")

    if self.options['overwrite_existing_translations'] and not self['update']:
        self.parser.error("the i18n-overwrite option cannot be used without the update option")

    if len(self['db_name']) > 1 and (self['init'] or self['update']):
        self.parser.error("Cannot use -i/--init or -u/--update with multiple databases in the -d/--database/db_name")

    # ensure default server wide modules are present
    if not self['server_wide_modules']:
        self._runtime_options['server_wide_modules'] = DEFAULT_SERVER_WIDE_MODULES
    for mod in REQUIRED_SERVER_WIDE_MODULES:
        if mod not in self['server_wide_modules']:
            self._log(logging.INFO, "adding missing %r to %s", mod, self.options_index['server_wide_modules'])
            self._runtime_options['server_wide_modules'] = [mod] + self['server_wide_modules']

    # ensure default http_interface is set
    if not self['http_interface']:
        self._runtime_options['http_interface'] = '127.0.0.1'

    # check here some envvar options that are exposed as property
    try:
        self.http_socket_activation
        self.max_http_threads
    except ValueError as exc:
        self.parser.error(exc.args[0])

    # accumulate all log_handlers
    self._runtime_options['log_handler'] = list(_deduplicate_loggers([
        *self._default_options.get('log_handler', []),
        *self._file_options.get('log_handler', []),
        *self._env_options.get('log_handler', []),
        *self._cli_options.get('log_handler', []),
    ]))

    self._runtime_options['init'] = dict.fromkeys(self['init'], True) or {}
    self._runtime_options['update'] = {'base': True} if 'all' in self['update'] else dict.fromkeys(self['update'], True)

    # TODO saas-22.1: remove support for the empty db_replica_host
    if self['db_replica_host'] == '':  # noqa: PLC1901
        self._runtime_options['db_replica_host'] = None
        if 'replica' not in self['dev_mode']:
            # Conditional warning so it is possible to have a single
            # config file (with db_replica_host= dev_mode=replica)
            # that works in both 18.0 and 19.0.
            # TODO saas-21.1:
            #   move this warning out of the if, as 18.0 won't be
            #   supported anymore, so people remove db_replica_host=
            #   from their config.
            self._warn((
                "Since 19.0, an empty {replica_host} was the 18.0 "
                "way to open a replica connection on the same "
                "server as {db_host}, for development/testing "
                "purpose, the feature now exists as {dev}=replica"
            ).format(
                replica_host=self.options_index['db_replica_host'],
                db_host=self.options_index['db_host'],
                dev=self.options_index['dev_mode'],
            ), DeprecationWarning)
            self._runtime_options['dev_mode'] = self['dev_mode'] + ['replica']

    if 'all' in self['dev_mode']:
        self._runtime_options['dev_mode'] = self['dev_mode'] + ALL_DEV_MODE

    if test_file := self['test_file']:
        if not os.path.isfile(test_file):
            self._log(logging.WARNING, f'test file {test_file!r} cannot be found')
        elif not test_file.endswith('.py'):
            self._log(logging.WARNING, f'test file {test_file!r} is not a python file')
        else:
            self._log(logging.INFO, 'Transforming --test-file into --test-tags')
            test_tags = (self['test_tags'] or '').split(',')
            test_tags.append(os.path.abspath(self['test_file']))
            self._runtime_options['test_tags'] = ','.join(test_tags)
            self._runtime_options['test_enable'] = True
    if self['test_enable'] and not self['test_tags']:
        self._runtime_options['test_tags'] = "+standard"
    self._runtime_options['test_enable'] = bool(self['test_tags'])
    if self._runtime_options['test_enable']:
        self._runtime_options['stop_after_init'] = True
        if not self['db_name']:
            self._log(logging.WARNING,
                "Empty %s, tests won't run", self.options_index['db_name'])


def _warn_deprecated_options(self):
    for old_option_name, new_option_name in self.aliases.items():
        for source_name, deprecated_value in self._get_sources(old_option_name).items():
            if deprecated_value is EMPTY:
                continue
            default_value = self._default_options[new_option_name]
            current_value = self[new_option_name]

            if deprecated_value in (current_value, default_value):
                # Surely this is from a --save that was run in a
                # prior version. There is no point in emitting a
                # warning because: (1) it holds the same value as
                # the correct option, and (2) it is going to be
                # automatically removed on the next --save anyway.
                self._log(logging.INFO,
                    f"The {old_option_name!r} option found in the "
                    f"{source_name} is a deprecated alias to "
                    f"{new_option_name!r}. The configuration value "
                    "is the same as the default value, it can "
                    "safely be removed.")
            elif current_value == default_value:
                # deprecated_value != current_value == default_value
                # assume the new option was not set
                self._runtime_options[new_option_name] = self.parse(new_option_name, deprecated_value)
                self._warn(
                    f"The {old_option_name!r} option found in the "
                    f"{source_name} is a deprecated alias to "
                    f"{new_option_name!r}, please use the latter.",
                    DeprecationWarning)
            else:
                # deprecated_value != current_value != default_value
                self.parser.error(
                    f"The two options {old_option_name!r} "
                    f"(found in the {source_name} but deprecated) "
                    f"and {new_option_name!r} are set to different "
                    "values. Please remove the first one and make "
                    "sure the second is correct."
                )
