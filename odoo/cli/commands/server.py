# Part of Odoo. See LICENSE file for full copyright and licensing details.

"""
OpenERP - Server
OpenERP is an ERP+CRM program for small and medium businesses.

The whole source code is distributed under the terms of the
GNU Public Licence.

(c) 2003-TODAY, Fabien Pinckaers - OpenERP SA
"""

import logging
import sys

from psycopg2.errors import InsufficientPrivilege

from odoo.release import author as __author__  # noqa: F401
from odoo.release import version as __version__  # noqa: F401
from odoo.service import server
from odoo.tools import config

from ..base import Command
from ..utils import check_postgres_user, check_root_user, report_configuration, setup_pid_file

# Also use the `odoo` logger for the main script.
_logger = logging.getLogger('odoo')



def main(args):
    check_root_user()
    config.parse_config(args, setup_logging=True)
    check_postgres_user()
    report_configuration()

    for db_name in config['db_name']:
        from odoo.modules import db  # noqa: PLC0415
        try:
            db._create_empty_database(db_name)
            config['init']['base'] = True
        except InsufficientPrivilege as err:
            # We use an INFO loglevel on purpose in order to avoid
            # reporting unnecessary warnings on build environment
            # using restricted database access.
            _logger.info("Could not determine if database %s exists, "
                         "skipping auto-creation: %s", db_name, err)
        except db.DatabaseExists:
            pass

    stop = config["stop_after_init"]

    setup_pid_file()
    rc = server.start(preload=config['db_name'], stop=stop)
    sys.exit(rc)


class Server(Command):
    """Start the odoo server (default command)"""

    def run(self, args):
        config.parser.prog = self.prog
        main(args)
