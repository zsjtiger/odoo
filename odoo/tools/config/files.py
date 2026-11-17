# Part of Odoo. See LICENSE file for full copyright and licensing details.
"""The configuration files: the loading of the options from a file and their saving."""

import configparser as ConfigParser
import logging
import os
import sys


from .options import DEFAULT_COLOR_SPEC


def _load_file_options(self, rcfile):
    self._file_options.clear()
    p = ConfigParser.RawConfigParser()
    try:
        p.read([rcfile])
        for (name, value) in p.items('options'):
            if name == 'without_demo':
                name = 'with_demo'
                value = str(self._check_without_demo(None, 'without_demo', value))
            option = self.options_index.get(name)
            if not option:
                if name not in self.aliases:
                    self._log(logging.WARNING,
                        "unknown option %r in the config file at "
                        "%s, option stored as-is, without parsing",
                        name, self['config'],
                    )
                self._file_options[name] = value
                continue
            if not option.file_loadable:
                continue
            if (
                value in ('False', 'false')
                and option.action not in ('store_true', 'store_false', 'callback')
                and option.nargs_ != '?'
            ):
                # "False" used to be the my_default of many non-bool options
                self._log(logging.WARNING, "option %s reads %r in the config file at %s but isn't a boolean option, skip", name, value, self['config'])
                continue
            self._file_options[name] = self.parse(name, value)
    except OSError:
        pass
    except ConfigParser.NoSectionError:
        pass


def save(self, keys=None):
    p = ConfigParser.RawConfigParser()
    rc_exists = os.path.exists(self['config'])
    if rc_exists and keys:
        p.read([self['config']])
    if not p.has_section('options'):
        p.add_section('options')
    if not p.has_section('colors'):
        p.add_section('colors')
    for opt in sorted(self.options):
        option = self.options_index.get(opt)
        if keys is not None and opt not in keys:
            continue
        if opt == 'version':
            continue
        if option:
            if option.file_exportable:
                pass
            elif option.file_loadable and self.options[opt] != self._default_options[opt]:
                # Persist the option if we can load it from the file
                # and that it is different from the default value.
                # Even if it was marked "file_exportable=False", we
                # just don't want to export the default value.
                pass
            else:
                continue
        if option:
            p.set('options', opt, self.format(opt, self.options[opt]))
        else:
            p.set('options', opt, self.options[opt])

    for color, value in DEFAULT_COLOR_SPEC.items():
        if color not in p['colors']:  # ignored unless keys are given
            p['colors'][color] = value

    # try to create the directories and write the file
    try:
        if not rc_exists and not os.path.exists(os.path.dirname(self['config'])):
            os.makedirs(os.path.dirname(self['config']))
        try:
            with open(self['config'], 'w', encoding='utf-8') as file:
                p.write(file)
            if not rc_exists:
                os.chmod(self['config'], 0o600)
        except OSError:
            sys.stderr.write("ERROR: couldn't write the config file\n")

    except OSError:
        # what to do if impossible?
        sys.stderr.write("ERROR: couldn't create the config directory\n")
