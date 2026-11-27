# Part of Odoo. See LICENSE file for full copyright and licensing details.

import sys
import textwrap

import odoo.cli
import odoo.release
from odoo.tools import config

from .base import PROG_NAME, commands
from .registry import find_command, load_addons_commands, load_internal_commands

# commands that were merged into another command, with their new invocation
MOVED_COMMANDS = {
    'neutralize': 'db neutralize',
    'obfuscate': 'db obfuscate',
}

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

    if command_name in MOVED_COMMANDS:
        sys.exit(f"'{command_name}' moved to '{PROG_NAME} {MOVED_COMMANDS[command_name]}'.")
    if command := find_command(command_name):
        odoo.cli.COMMAND = command_name
        command().run(args)
    else:
        message = (
            f"Unknown command {command_name!r}.\n"
            f"Use '{PROG_NAME} --help' to see the list of available commands."
        )
        sys.exit(message)
