# Part of Odoo. See LICENSE file for full copyright and licensing details.

import sys
import traceback
from pathlib import Path

import odoo.addons
from odoo.modules import initialize_sys_path, load_script

from .base import Command, commands


def load_internal_commands():
    """ Load ``commands`` from ``odoo.cli.commands`` (private modules are skipped) """
    import odoo.cli.commands  # noqa: PLC0415
    for path in odoo.cli.commands.__path__:
        for module in Path(path).iterdir():
            if module.name.startswith('_'):
                continue
            if module.suffix == '.py' or (module / '__init__.py').is_file():
                __import__(f'odoo.cli.commands.{module.stem}')


def load_addons_commands(command=None):
    """
    Search the addons path for modules with a ``cli/{command}.py`` file.
    In case no command is provided, discover and load all the commands.
    """
    if command is None:
        command = '*'
    elif not Command.is_valid_name(command):
        return

    mapping = {}
    initialize_sys_path()
    for path in odoo.addons.__path__:
        for fullpath in Path(path).glob(f'*/cli/{command}.py'):
            if (found_command := fullpath.stem) and Command.is_valid_name(found_command):
                # loading as odoo.cli and not odoo.addons.{module}.cli
                # so it doesn't load odoo.addons.{module}.__init__
                mapping[f'odoo.cli.{found_command}'] = fullpath

    for fq_name, fullpath in mapping.items():
        try:
            load_script(fullpath, fq_name)
        except ImportError:
            print("Couldn't load", fullpath, file=sys.stderr)  # noqa: T201
            traceback.print_exc()


def find_command(name: str) -> Command | None:
    """ Get command by name. """

    # built-in commands
    if command := commands.get(name):
        return command

    # import from odoo.cli.commands
    try:
        __import__(f'odoo.cli.commands.{name}')
    except ModuleNotFoundError as exc:
        if f"'odoo.cli.commands.{name}'" not in exc.args[0]:
            raise
    else:
        return commands[name]

    # import from odoo.addons.*.cli
    load_addons_commands(command=name)
    return commands.get(name)
