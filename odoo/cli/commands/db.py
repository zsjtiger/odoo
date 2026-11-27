import io
import logging
import sys
import textwrap
import urllib.parse
import zipfile
from argparse import RawTextHelpFormatter
from functools import partial
from pathlib import Path

import requests

import odoo.modules.neutralize
import odoo.orm.database.sql_db

from ...modules import db
from ...tools import config
from ..base import Command
from ..utils import report_configuration
from ._obfuscate import Obfuscator

_logger = logging.getLogger(__name__)

eprint = partial(print, file=sys.stderr, flush=True)


_db_exist_error_message = """\
Target database {db_name} exists, aborting.

\tuse `--force` to delete the existing database anyway."""


def _exit_if_exists(db_name, *, drop_instead):
    if not db.exist(db_name):
        pass
    elif drop_instead:
        db.drop(db_name)
    else:
        sys.exit(_db_exist_error_message.format(db_name=db_name))


class Db(Command):
    """ Create, drop, dump, load databases """
    name = 'db'
    description = """
        Command-line version of the database manager.

        Commands are all filestore-aware.
    """

    def run(self, cmdargs):
        parser = self.parser
        parser.add_argument('-c', '--config')
        parser.add_argument('-D', '--data-dir')
        parser.add_argument('--addons-path')
        parser.add_argument('-r', '--db_user')
        parser.add_argument('-w', '--db_password')
        parser.add_argument('--pg_path')
        parser.add_argument('--db_host')
        parser.add_argument('--db_port')
        parser.add_argument('--db_sslmode')
        parser.set_defaults(func=lambda _: exit(parser.format_help()))

        subs = parser.add_subparsers()

        self._add_init_parser(subs)
        self._add_load_parser(subs)
        self._add_dump_parser(subs)
        self._add_duplicate_parser(subs)
        self._add_rename_parser(subs)
        self._add_drop_parser(subs)
        self._add_neutralize_parser(subs)
        self._add_obfuscate_parser(subs)

        args = parser.parse_args(cmdargs)

        config.parse_config([
            val
            for k, v in vars(args).items()
            if v is not None
            if k in ['config', 'data_dir', 'addons_path'] or k.startswith(('db_', 'pg_'))
            for val in [
                '--data-dir' if k == 'data_dir'
                    else '--addons-path' if k == 'addons_path'
                    else f'--{k}',
                v,
            ]
        ], setup_logging=True)
        report_configuration()

        args.func(args)

    def _add_init_parser(self, subs):
        # INIT ----------------------------------

        init = subs.add_parser(
            "init",
            help="Create and initialize a database",
            description="Create an empty database and install the minimum required modules",
            formatter_class=RawTextHelpFormatter,
        )
        init.set_defaults(func=self.init)
        init.add_argument(
            'database',
            help="database to create",
        )
        init.add_argument(
            '--with-demo', action='store_true',
            help="install demo data in the new database",
        )
        init.add_argument(
            '--force', action='store_true',
            help="delete database if exists",
        )
        init.add_argument(
            '--language', default='en_US',
            help="default language for the instance, default 'en_US'",
        )
        init.add_argument(
            '--username', default='admin',
            help="admin username, default 'admin'",
        )
        init.add_argument(
            '--password', default='admin',
            help="admin password, default 'admin'",
        )
        init.add_argument(
            '--country',
            help="country to be set on the main company",
        )
        init.epilog = textwrap.dedent("""\

                Database initialization will install the minimum required modules.
                To install more modules, use the `module install` command.
                For more info:

                $ cross-cli.py module install --help
        """)

    def _add_load_parser(self, subs):
        # LOAD ----------------------------------

        load = subs.add_parser(
            "load", help="Load a dump file.",
            description="Loads a dump file into odoo, dump file can be a URL. "
                 "If `database` is provided, uses that as the database name. "
                 "Otherwise uses the dump file name without extension.")
        load.set_defaults(func=self.load)
        load.add_argument(
            '-f', '--force', action='store_const', default=False, const=True,
            help="delete `database` database before loading if it exists"
        )
        load.add_argument(
            '-n', '--neutralize', action='store_const', default=False, const=True,
            help="neutralize the database after restore"
        )
        load.add_argument(
            '--move', dest='copy', action='store_const', default=True, const=False,
            help="restore as a moved database, keeping its UUID instead of generating a new one"
        )
        load.add_argument(
            'database', nargs='?',
            help="database to create, defaults to dump file's name "
                 "(without extension)"
        )
        load.add_argument('dump_file', help="zip or pg_dump file to load")

    def _add_dump_parser(self, subs):
        # DUMP ----------------------------------

        dump = subs.add_parser(
            "dump", help="Create a dump with filestore.",
            description="Creates a dump file. The dump is always in zip format "
                        "(with filestore), to get pg_dump format, use "
                        "dump_format argument.")
        dump.set_defaults(func=self.dump)
        dump.add_argument('database', help="database to dump")
        dump.add_argument(
            'dump_path', nargs='?', default='-',
            help="if provided, database is dumped to specified path, otherwise "
                 "or if `-`, dumped to stdout",
        )
        dump.add_argument(
            '--format', dest='dump_format', choices=('zip', 'dump'), default='zip',
            help="if provided, database is dumped used the specified format, "
                "otherwise defaults to `zip`.\n"
                "Supported formats are `zip`, `dump` (pg_dump format) ",
        )
        dump.add_argument(
            '--no-filestore', action='store_const', dest='filestore', default=True, const=False,
            help="if passed, zip database is dumped without filestore (default: false)"
        )

    def _add_duplicate_parser(self, subs):
        # DUPLICATE -----------------------------

        duplicate = subs.add_parser("duplicate", help="Duplicate a database including filestore.")
        duplicate.set_defaults(func=self.duplicate)
        duplicate.add_argument(
            '-f', '--force', action='store_const', default=False, const=True,
            help="delete `target` database before copying if it exists"
        )
        duplicate.add_argument(
            '-n', '--neutralize', action='store_const', default=False, const=True,
            help="neutralize the target database after duplicate"
        )
        duplicate.add_argument("source")
        duplicate.add_argument("target", help="database to copy `source` to, must not exist unless `-f` is specified in which case it will be dropped first")

    def _add_rename_parser(self, subs):
        # RENAME --------------------------------

        rename = subs.add_parser("rename", help="Rename a database including filestore.")
        rename.set_defaults(func=self.rename)
        rename.add_argument(
            '-f', '--force', action='store_const', default=False, const=True,
            help="delete `target` database before renaming if it exists"
        )
        rename.add_argument('source')
        rename.add_argument("target", help="database to rename `source` to, must not exist unless `-f` is specified, in which case it will be dropped first")

    def _add_drop_parser(self, subs):
        # DROP ----------------------------------

        drop = subs.add_parser("drop", help="Delete a database including filestore")
        drop.set_defaults(func=self.drop)
        drop.add_argument("database", help="database to delete")

    def _add_neutralize_parser(self, subs):
        neutralize = subs.add_parser(
            "neutralize",
            help="Neutralize a database for testing: no emails sent, etc.",
        )
        neutralize.set_defaults(func=self.neutralize)
        neutralize.add_argument("database", help="database to neutralize")
        neutralize.add_argument(
            "--stdout", action="store_true",
            help="Output the neutralization SQL instead of applying it",
        )

    def _add_obfuscate_parser(self, subs):
        obfuscate = subs.add_parser(
            "obfuscate",
            help="Obfuscate (or unobfuscate) data of a database",
        )
        obfuscate.set_defaults(func=self.obfuscate)
        obfuscate.add_argument("database", help="database to obfuscate")
        obfuscate.add_argument("--pwd", required=True, help="Cypher password")
        obfuscate.add_argument(
            "--fields",
            help="List of table.columns to obfuscate/unobfuscate: table1.column1,table2.column1,table2.column2",
        )
        obfuscate.add_argument(
            "--exclude",
            help="List of table.columns to exclude from obfuscate/unobfuscate: table1.column1,table2.column1,table2.column2",
        )
        obfuscate.add_argument("--file", help="File containing the list of table.columns to obfuscate/unobfuscate")
        obfuscate.add_argument("--unobfuscate", action="store_true", help="Unobfuscate the data instead")
        obfuscate.add_argument(
            "--allfields", action="store_true",
            help="Used in unobfuscate mode, try to unobfuscate all fields. Cannot be used in obfuscate mode. "
                 "Slower than specifying fields.",
        )
        obfuscate.add_argument("--vacuum", action="store_true", help="Vacuum database after unobfuscating")
        obfuscate.add_argument(
            "--pertablecommit", action="store_true",
            help="Commit after each table instead of a big transaction",
        )
        obfuscate.add_argument(
            "-y", "--yes", action="store_true",
            help="Don't ask for manual confirmation. Use it carefully as the obfuscate method is not considered "
                 "as safe to transfer anonymous datas to a third party.",
        )

    def neutralize(self, args):
        try:
            with odoo.orm.database.sql_db.db_connect(args.database).cursor() as cursor:
                if args.stdout:
                    installed_modules = odoo.modules.neutralize.get_installed_modules(cursor)
                    queries = odoo.modules.neutralize.get_neutralization_queries(installed_modules)
                    # pylint: disable=bad-builtin
                    print('BEGIN;')
                    for query in queries:
                        # pylint: disable=bad-builtin
                        print(query.rstrip(";") + ";")
                    # pylint: disable=bad-builtin
                    print("COMMIT;")
                else:
                    _logger.info("Starting %s database neutralization", args.database)
                    odoo.modules.neutralize.neutralize_database(cursor)
        except Exception:
            _logger.critical("An error occurred during the neutralization. THE DATABASE IS NOT NEUTRALIZED!")
            sys.exit(1)

    def obfuscate(self, args):
        Obfuscator().run(args)

    def init(self, args):
        _exit_if_exists(args.database, drop_instead=args.force)
        db.create(
            db_name=args.database,
            demo=args.with_demo,
            lang=args.language,
            user_login=args.username,
            user_password=args.password,
            country_code=args.country,
            phone=None,
        )

    def load(self, args):
        db_name = args.database or Path(args.dump_file).stem
        _exit_if_exists(db_name, drop_instead=args.force)

        url = urllib.parse.urlparse(args.dump_file)
        if url.scheme:
            eprint(f"Fetching {args.dump_file}...", end='')
            r = requests.get(args.dump_file, timeout=10)
            if not r.ok:
                exit(f" unable to fetch {args.dump_file}: {r.reason}")

            eprint(" done")
            dump_file = io.BytesIO(r.content)
        else:
            eprint(f"Restoring {args.dump_file}...")
            dump_file = args.dump_file

        if not zipfile.is_zipfile(dump_file):
            exit("Not a zipped dump file, use `pg_restore` to restore raw dumps,"
                 " and `psql` to execute sql dumps or scripts.")

        db.restore(
            db_name,
            dump_file,
            copy=args.copy,
            neutralize_database=args.neutralize,
        )

    def dump(self, args):
        if args.dump_path == '-':
            db.dump(args.database, sys.stdout.buffer)
        else:
            with open(args.dump_path, 'wb') as dump_file:
                db.dump(
                    args.database,
                    dump_file,
                    backup_format=args.dump_format,
                    with_filestore=args.filestore,
                )

    def duplicate(self, args):
        _exit_if_exists(args.target, drop_instead=args.force)
        db.duplicate(
            args.source,
            args.target,
            neutralize_database=args.neutralize,
        )

    def rename(self, args):
        _exit_if_exists(args.target, drop_instead=args.force)
        db.rename(
            args.source,
            args.target,
        )

    def drop(self, args):
        db.drop(args.database)
