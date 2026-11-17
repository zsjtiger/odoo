# Part of Odoo. See LICENSE file for full copyright and licensing details.
"""Checks and formats of the options: the addons paths, the scripts, the booleans, the lists and the paths."""

import glob
import logging
import optparse
import os




def _is_addons_path(cls, path):
    for f in os.listdir(path):
        modpath = os.path.join(path, f)

        def hasfile(filename):
            return os.path.isfile(os.path.join(modpath, filename))
        if hasfile('__init__.py') and hasfile('__manifest__.py'):
            return True
    return False


def _check_addons_path(cls, option, opt, value):
    ad_paths = []
    for path in map(cls._normalize, cls._check_comma(option, opt, value)):
        if glob.has_magic(path):
            ad_paths.extend(sorted(p for p in glob.glob(path) if os.path.isdir(p) and cls._is_addons_path(p)))
            continue
        if not os.path.isdir(path):
            cls._log(logging.WARNING, "option %s, no such directory %r, skipped", opt, path)
            continue
        if not cls._is_addons_path(path):
            cls._log(logging.WARNING, "option %s, invalid addons directory %r, skipped", opt, path)
            continue
        ad_paths.append(path)
    return ad_paths


def _check_upgrade_path(cls, option, opt, value):
    upgrade_path = []
    for path in map(cls._normalize, cls._check_comma(option, opt, value)):
        if not os.path.isdir(path):
            cls._log(logging.WARNING, "option %s, no such directory %r, skipped", opt, path)
            continue
        if not cls._is_upgrades_path(path):
            cls._log(logging.WARNING, "option %s, invalid upgrade directory %r, skipped", opt, path)
            continue
        if path not in upgrade_path:
            upgrade_path.append(path)
    return upgrade_path


def _check_scripts(cls, option, opt, value):
    pre_upgrade_scripts = []
    for path in map(cls._normalize, cls._check_comma(option, opt, value)):
        if not os.path.isfile(path):
            cls._log(logging.WARNING, "option %s, no such file %r, skipped", opt, path)
            continue
        if path not in pre_upgrade_scripts:
            pre_upgrade_scripts.append(path)
    return pre_upgrade_scripts


def _is_upgrades_path(cls, path):
    module = '*'
    version = '*'
    return any(
        glob.glob(os.path.join(path, f'{module}/{version}/{prefix}-*.py'))
        for prefix in ['pre', 'post', 'end']
    )


def _check_bool(cls, option, opt, value):
    if value.lower() in ('1', 'yes', 'true', 'on'):
        return True
    if value.lower() in ('0', 'no', 'false', 'off'):
        return False
    raise optparse.OptionValueError(
        f"option {opt}: invalid boolean value: {value!r}"
    )


def _check_comma(cls, option_name, option, value):
    return [v for s in value.split(',') if (v := s.strip())]


def _check_path(cls, option, opt, value):
    return cls._normalize(value)


def _check_without_demo(cls, option, opt, value):
    try:
        return not cls._check_bool(option, opt, value)
    except optparse.OptionValueError:
        cls._log(logging.WARNING, "option %s: since 19.0, invalid boolean value: %r, assume %s", opt, value, value != 'None')
        return value == 'None'


def _format_string(cls, value):
    return str(value)


def _format_list(cls, value):
    return ','.join(filter(bool, (str(elem).strip() for elem in value)))


def _format_without_demo(cls, value):
    return str(bool(value))


def format_config(self, option_name, value):
    option = self.options_index[option_name]
    if option.action in ('store_true', 'store_false'):
        format_func = self.parser.option_class.TYPE_FORMATTER['bool']
    else:
        format_func = self.parser.option_class.TYPE_FORMATTER[option.type]
    return format_func(value)
