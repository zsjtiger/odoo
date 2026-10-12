import argparse
import re
import sys
import textwrap
import traceback
from inspect import cleandoc
from pathlib import Path

import odoo.core.bootstrap  # noqa: F401  # import first for core setup
import odoo.orm  # noqa: F401
import odoo.addons
import odoo.cli
import odoo.release
from odoo.modules import initialize_sys_path, load_script
from odoo.tools import config

COMMAND_NAME_RE = re.compile(r'^[a-z][a-z0-9_]*$', re.I)
PROG_NAME = Path(sys.argv[0]).name
commands = {}
"""All loaded commands"""


class Command:
    name = None
    description = None
    epilog = None
    _parser = None

    def __init_subclass__(cls):
        cls.name = cls.name or cls.__name__.lower()
        module = cls.__module__.rpartition('.')[2]
        if not cls.is_valid_name(cls.name):
            raise ValueError(
                f"Command name {cls.name!r} "
                f"must match {COMMAND_NAME_RE.pattern!r}")
        if cls.name != module:
            raise ValueError(
                f"Command name {cls.name!r} "
                f"must match Module name {module!r}")
        commands[cls.name] = cls

    @property
    def prog(self):
        return f"{PROG_NAME} [--addons-path=PATH,...] {self.name}"

    @property
    def parser(self):
        if not self._parser:
            self._parser = argparse.ArgumentParser(
                formatter_class=argparse.RawDescriptionHelpFormatter,
                prog=self.prog,
                description=cleandoc(self.description or self.__doc__ or ""),
                epilog=cleandoc(self.epilog or ""),
            )
        return self._parser

    @classmethod
    def is_valid_name(cls, name):
        return re.match(COMMAND_NAME_RE, name)


def load_internal_commands():
    """ Load ``commands`` from ``odoo.cli`` """
    for path in odoo.cli.__path__:
        for module in Path(path).iterdir():
            if module.suffix == '.py' or (module / '__init__.py').is_file():
                __import__(f'odoo.cli.{module.stem}')


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

    # import from odoo.cli
    try:
        __import__(f'odoo.cli.{name}')
    except ModuleNotFoundError as exc:
        if f"'odoo.cli.{name}'" not in exc.args[0]:
            raise
    else:
        return commands[name]

    # import from odoo.addons.*.cli
    load_addons_commands(command=name)
    return commands.get(name)


HELP_TEMPLATE = textwrap.dedent("""\
    usage: {prog_name} [--addons-path=PATH,...] <command> [...]

    Odoo {version}
    Available commands:

    {command_list}

    Use '{prog_name} server --help' for regular server options.
    Use '{prog_name} <command> --help' for other individual commands options.
""")


def show_help():
    """ Print the list of available commands """
    load_internal_commands()
    load_addons_commands()

    padding = max(len(cmd_name) for cmd_name in commands) + 2
    command_list = "\n".join(
        f"    {name:<{padding}}{(cmd.__doc__ or '').strip()}"
        for name, cmd in sorted(commands.items())
    )
    print(HELP_TEMPLATE.format(  # noqa: T201
        prog_name=PROG_NAME,
        version=odoo.release.version,
        command_list=command_list,
    ))


def main():
    args = sys.argv[1:]

    # The only shared option is '--addons-path=' needed to discover additional
    # commands from modules
    if len(args) > 1 and args[0].startswith('--addons-path=') and not args[1].startswith('-'):
        # parse only the addons-path, do not setup the logger...
        config._parse_config([args[0]])
        args = args[1:]

    if len(args) and not args[0].startswith('-'):
        # Command specified, search for it
        command_name = args[0]
        args = args[1:]
    elif '-h' in args or '--help' in args:
        # No command specified, but help is requested
        show_help()
        return
    else:
        # No command specified, default command used
        command_name = 'server'

    if command_name == 'help':
        show_help()
        return

    if command := find_command(command_name):
        odoo.cli.COMMAND = command_name
        command().run(args)
    else:
        message = (
            f"Unknown command {command_name!r}.\n"
            f"Use '{PROG_NAME} --help' to see the list of available commands."
        )
        sys.exit(message)
