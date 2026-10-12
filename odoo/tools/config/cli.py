# Part of Odoo. See LICENSE file for full copyright and licensing details.
"""The command line options of the server: their definitions and their defaults."""

import optparse
import os
import sys
import tempfile
from odoo import release
from odoo.tools.system import appdirs


from .options import DEFAULT_SERVER_WIDE_MODULES, OdooOptionParser, _FileOnlyOption, _OdooOption, _PosixOnlyOption


def _build_cli(self):
    OdooOption = type('OdooOption', (_OdooOption,), {'config': self})
    FileOnlyOption = type('FileOnlyOption', (_FileOnlyOption, OdooOption), {})
    PosixOnlyOption = type('PosixOnlyOption', (_PosixOnlyOption, OdooOption), {})

    version = "%s %s" % (release.description, release.version)
    parser = OdooOptionParser(version=version, option_class=OdooOption)

    parser.add_option(FileOnlyOption(dest='admin_passwd', my_default='admin'))
    parser.add_option(FileOnlyOption(dest='bin_path', type='path', my_default='', file_exportable=False))
    parser.add_option(FileOnlyOption(dest='csv_internal_sep', my_default=','))
    parser.add_option(FileOnlyOption(dest='default_productivity_apps', type='bool', my_default=False, file_exportable=False))
    parser.add_option(FileOnlyOption(dest='import_file_maxbytes', type='int', my_default=10 * 1024 * 1024, file_exportable=False))
    parser.add_option(FileOnlyOption(dest='import_file_timeout', type='int', my_default=3, file_exportable=False))
    parser.add_option(FileOnlyOption(dest='import_url_regex', my_default=r"^(?:http|https)://", file_exportable=False))
    parser.add_option(FileOnlyOption(dest='proxy_access_token', my_default='', file_exportable=False))
    parser.add_option(FileOnlyOption(dest='publisher_warranty_url', my_default='http://services.odoo.com/publisher-warranty/', file_exportable=False))
    parser.add_option(FileOnlyOption(dest='reportgz', action='store_true', my_default=False))
    parser.add_option(FileOnlyOption(dest='websocket_keep_alive_timeout', type='int', my_default=3600))
    parser.add_option(FileOnlyOption(dest='websocket_rate_limit_burst', type='int', my_default=10))
    parser.add_option(FileOnlyOption(dest='websocket_rate_limit_delay', type='float', my_default=0.2))

    # Server startup config
    group = optparse.OptionGroup(parser, "Common options")
    group.add_option("-c", "--config", dest="config", type='path', file_loadable=False, env_name='ODOO_RC',
                     help="specify alternate config file")
    group.add_option("--save", action="store_true", dest="save", my_default=False, file_loadable=False,
                     help="save configuration to ~/.odoorc (or to ~/.openerp_serverrc if it exists)")
    group.add_option("-i", "--init", dest="init", type='comma', metavar="MODULE,...", my_default=[], file_loadable=False,
                     help="install one or more modules (comma-separated list, use \"all\" for all modules), requires -d")
    group.add_option("-u", "--update", dest="update", type='comma', metavar="MODULE,...", my_default=[], file_loadable=False,
                     help="update one or more modules (comma-separated list, use \"all\" for all modules). Requires -d.")
    group.add_option("--reinit", dest="reinit", type='comma', metavar="MODULE,...", my_default=[], file_loadable=False,
                     help="reinitialize one or more modules (comma-separated list), requires -d")
    group.add_option("--with-demo", dest="with_demo", action='store_true', my_default=False,
                     help="install demo data in new databases")
    group.add_option("--without-demo", dest="with_demo", type='without_demo', metavar='BOOL', const=True,
                     nargs='?',  # ty:ignore[invalid-argument-type]
                     help="don't install demo data in new databases (default)")
    group.add_option("--skip-auto-install", dest="skip_auto_install", action="store_true", my_default=False,
                     help="skip the automatic installation of modules marked as auto_install")
    group.add_option("-P", "--import-partial", dest="import_partial", type='path', my_default='', file_loadable=False,
                     help="Use this for big data importation, if it crashes you will be able to continue at the current state. Provide a filename to store intermediate importation states.")
    group.add_option("--pidfile", dest="pidfile", type='path', my_default='',
                     help="file where the server pid will be stored")
    group.add_option("--addons-path", dest="addons_path", type='addons_path', metavar='PATH,...', my_default=[],
                     help="specify additional addons paths (separated by commas).")
    group.add_option("--upgrade-path", dest="upgrade_path", type='upgrade_path', metavar='PATH,...', my_default=[],
                     help="specify an additional upgrade path.")
    group.add_option('--pre-upgrade-scripts', dest='pre_upgrade_scripts', type='pre_upgrade_scripts', metavar='PATH,...', my_default=[],
                     help="Run specific upgrade scripts before loading any module when -u is provided.")
    group.add_option("--load", dest="server_wide_modules", type='comma', metavar='MODULE,...', my_default=DEFAULT_SERVER_WIDE_MODULES,
                     help="Comma-separated list of server-wide modules.")
    group.add_option("-D", "--data-dir", dest="data_dir", type='path',  # sensitive default set in _load_default_options
                     help="Directory where to store Odoo data")
    group.add_option("--unsafe-policy", dest='unsafe_policy', type='choice', my_default='log',
                     choices=['disable', 'log', 'raise', 'terminate'],
                     help="Policy if an unsafe object is detected during          "
                          "arbitrary code execution                               "
                          "- disable: No action taken                             "
                          "- log: Log a warning with unsafe object information    "
                          "- raise: Raise an exception (BaseException)            "
                          "- terminate: Terminate the current worker process      ")
    parser.add_option_group(group)

    # HTTP
    group = optparse.OptionGroup(parser, "HTTP Service Configuration")
    group.add_option("--http-interface", dest="http_interface", my_default='127.0.0.1',
                     help="Listen interface address for HTTP services.")
    group.add_option("-p", "--http-port", dest="http_port", my_default=8069,
                     help="Listen port for the main HTTP service", type="int", metavar="PORT")
    group.add_option("--gevent-port", dest="gevent_port", my_default=8072,
                     help="Listen port for the gevent worker", type="int", metavar="PORT")
    group.add_option("--no-http", dest="http_enable", action="store_false", my_default=True,
                     help="Disable the HTTP and Longpolling services entirely")
    group.add_option("--proxy-mode", dest="proxy_mode", action="store_true", my_default=False,
                     help="Activate reverse proxy WSGI wrappers (headers rewriting) "
                          "Only enable this when running behind a trusted web proxy!")
    group.add_option("--x-sendfile", dest="x_sendfile", action="store_true", my_default=False,
                     help="Activate X-Sendfile (apache) and X-Accel-Redirect (nginx) "
                          "HTTP response header to delegate the delivery of large "
                          "files (assets/attachments) to the web server.")
    parser.add_option_group(group)

    # WEB
    group = optparse.OptionGroup(parser, "Web interface Configuration")
    group.add_option("--db-filter", dest="dbfilter", my_default='', metavar="REGEXP",
                     help="Regular expressions for filtering available databases for Web UI. "
                          "The expression can use %d (domain) and %h (host) placeholders.")
    parser.add_option_group(group)

    # Testing Group
    group = optparse.OptionGroup(parser, "Testing Configuration")
    group.add_option("--test-file", dest="test_file", type='path', my_default='', file_loadable=False,
                     help="Launch a python test file.")
    group.add_option("--test-enable", dest='test_enable', action="store_true", file_loadable=False,
                     help="Enable unit tests. Implies --stop-after-init")
    group.add_option("-t", "--test-tags", dest="test_tags", file_loadable=False,
                     help="Comma-separated list of specs to filter which tests to execute. Enable unit tests if set. "
                     "A filter spec has the format: [-][tag][/module][:class][.method][[params]] "
                     "The '-' specifies if we want to include or exclude tests matching this spec. "
                     "The tag will match tags added on a class with a @tagged decorator "
                     "(all Test classes have 'standard' and 'post_install' tags "
                     "until explicitly removed, see the decorator documentation). "
                     "'*' will match all tags. "
                     "If tag is omitted on include mode, its value is 'standard'. "
                     "If tag is omitted on exclude mode, its value is '*'. "
                     "The module, class, and method will respectively match the module name, test class name and test method name. "
                     "Example: --test-tags :TestClass.test_func,/test_module,external "
                     "It is also possible to provide parameters to a test method that supports them"
                     "Example: --test-tags /web.test_js[mail]"
                     "If negated, a test-tag with parameter will negate the parameter when passing it to the test"

                     "Filtering and executing the tests happens twice: right "
                     "after each module installation/update and at the end "
                     "of the modules loading. At each stage tests are filtered "
                     "by --test-tags specs and additionally by dynamic specs "
                     "'at_install' and 'post_install' correspondingly. Implies --stop-after-init")

    group.add_option("--screencasts", dest="screencasts", type='path', my_default='',
                     metavar='DIR',
                     help="Screencasts will go in DIR/{db_name}/screencasts.")
    temp_tests_dir = os.path.join(tempfile.gettempdir(), 'odoo_tests')
    group.add_option("--screenshots", dest="screenshots", type='path', my_default=temp_tests_dir,
                     metavar='DIR',
                     help="Screenshots will go in DIR/{db_name}/screenshots. Defaults to %s." % temp_tests_dir)
    parser.add_option_group(group)

    # Logging Group
    group = optparse.OptionGroup(parser, "Logging Configuration")
    group.add_option("--logfile", dest="logfile", type='path', my_default='',
                     help="file where the server log will be stored")
    group.add_option("--syslog", action="store_true", dest="syslog", my_default=False,
                     help="Send the log to the syslog server (deprecated)")
    group.add_option('--log-handler', action="append", type='comma', my_default=[':INFO'], metavar="MODULE:LEVEL",
                     help='setup a handler at LEVEL for a given MODULE. An empty MODULE indicates the root logger. '
                          'This option can be repeated. Example: "odoo.orm:DEBUG" or "werkzeug:CRITICAL" (default: ":INFO")')
    group.add_option('--log-web', action="append_const", dest="log_handler", const=("odoo.http:DEBUG",),
                     help='shortcut for --log-handler=odoo.http:DEBUG')
    group.add_option('--log-sql', action="append_const", dest="log_handler", const=("odoo.sql_db:DEBUG",),
                     help='shortcut for --log-handler=odoo.sql_db:DEBUG')
    group.add_option('--log-db', dest='log_db', help="Logging database", my_default='')
    group.add_option('--log-db-level', dest='log_db_level', my_default='warning', help="Logging database level")
    group.add_option('--log-config', dest='log_config', type='path', my_default='',
                     help="JSON logging configuration file, in dictconfig format ("
                          "https://docs.python.org/3/library/logging.config.html#logging-config-dictschema).")
    # For backward-compatibility, map the old log levels to something
    # quite close.
    levels = [
        'info', 'debug_rpc', 'warn', 'test', 'critical', 'runbot',
        'debug_sql', 'error', 'debug', 'debug_rpc_answer', 'notset'
    ]
    group.add_option('--log-level', dest='log_level', type='choice',
                     choices=levels, my_default='info',
                     help='specify the level of the logging. Accepted values: %s.' % (levels,))

    parser.add_option_group(group)

    # SMTP Group
    group = optparse.OptionGroup(parser, "SMTP Configuration")
    group.add_option('--email-from', dest='email_from', my_default='',
                     help='specify the SMTP email address for sending email')
    group.add_option('--from-filter', dest='from_filter', my_default='',
                     help='specify for which email address the SMTP configuration can be used')
    group.add_option('--smtp', dest='smtp_server', my_default='localhost',
                     help='specify the SMTP server for sending email')
    group.add_option('--smtp-port', dest='smtp_port', my_default=25,
                     help='specify the SMTP port', type="int")
    group.add_option('--smtp-ssl', dest='smtp_ssl', action='store_true', my_default=False,
                     help='if passed, SMTP connections will be encrypted with SSL (STARTTLS)')
    group.add_option('--smtp-user', dest='smtp_user', my_default='',
                     help='specify the SMTP username for sending email')
    group.add_option('--smtp-password', dest='smtp_password', my_default='',
                     help='specify the SMTP password for sending email')
    group.add_option('--smtp-ssl-certificate-filename', dest='smtp_ssl_certificate_filename', type='path', my_default='',
                     help='specify the SSL certificate used for authentication')
    group.add_option('--smtp-ssl-private-key-filename', dest='smtp_ssl_private_key_filename', type='path', my_default='',
                     help='specify the SSL private key used for authentication')
    parser.add_option_group(group)

    # Database Group
    group = optparse.OptionGroup(parser, "Database related options")
    group.add_option("-d", "--database", dest="db_name", type='comma', metavar="DATABASE,...", my_default=[], env_name='PGDATABASE',
                     help="database(s) used when installing or updating modules.")
    group.add_option("-r", "--db_user", dest="db_user", my_default='', env_name='PGUSER',
                     help="specify the database user name")
    group.add_option("-w", "--db_password", dest="db_password", my_default='', env_name='PGPASSWORD',
                     help="specify the database password")
    group.add_option("--pg_path", dest="pg_path", type='path', my_default='', env_name='PGPATH',
                     help="specify the pg executable path")
    group.add_option("--db_host", dest="db_host", my_default='', env_name='PGHOST',
                     help="specify the database host")
    group.add_option("--db_replica_host", dest="db_replica_host", my_default=None, env_name='PGHOST_REPLICA',
                     help="specify the replica host")
    group.add_option("--db_port", dest="db_port", my_default=None, env_name='PGPORT',
                     help="specify the database port", type="int")
    group.add_option("--db_replica_port", dest="db_replica_port", my_default=None, env_name='PGPORT_REPLICA',
                     help="specify the replica port", type="int")
    group.add_option("--db_sslmode", dest="db_sslmode", type="choice", my_default='prefer', env_name='PGSSLMODE',
                     choices=['disable', 'allow', 'prefer', 'require', 'verify-ca', 'verify-full'],
                     help="specify the database ssl connection mode (see PostgreSQL documentation)")
    group.add_option("--db_app_name", dest="db_app_name", my_default="odoo-{pid}", env_name='PGAPPNAME',
                     help="specify the application name in the database, {pid} is substituted by the process pid")
    group.add_option("--db_maxconn", dest="db_maxconn", type='int', my_default=64,
                     help="specify the maximum number of physical connections to PostgreSQL")
    group.add_option("--db_maxconn_gevent", dest="db_maxconn_gevent", type='int', my_default=None,
                     help="specify the maximum number of physical connections to PostgreSQL specifically for the gevent worker")
    group.add_option("--db-template", dest="db_template", my_default="template0", env_name='PGDATABASE_TEMPLATE',
                     help="specify a custom database template to create a new database")
    group.add_option("--db-system", dest="db_system", my_default="postgres", env_name='PGDATABASE_SYSTEM',
                     help="specify the database for shared system operations like bus and maintenance")
    parser.add_option_group(group)

    # i18n Group
    group = optparse.OptionGroup(parser, "Internationalisation options",
        "Use these options to translate Odoo to another language. "
        "See i18n section of the user manual. Option '-d' is mandatory. "
        "Option '-l' is mandatory in case of importation"
        )
    group.add_option('--load-language', dest="load_language", file_exportable=False,
                     help="specifies the languages for the translations you want to be loaded")
    group.add_option("--i18n-overwrite", dest="overwrite_existing_translations", action="store_true", my_default=False, file_exportable=False,
                     help="overwrites existing translation terms on updating a module.")
    parser.add_option_group(group)

    # Security Group
    security = optparse.OptionGroup(parser, 'Security-related options')
    security.add_option('--no-database-list', action="store_false", dest='list_db', my_default=True,
                        help="Disable the ability to obtain or view the list of databases. "
                             "Also disable access to the database manager and selector, "
                             "so be sure to set a proper --database parameter first")
    parser.add_option_group(security)

    # Advanced options
    group = optparse.OptionGroup(parser, "Advanced options")
    group.add_option('--dev', dest='dev_mode', type='comma', metavar="FEATURE,...", my_default=[], file_exportable=False, env_name='ODOO_DEV',
                     # optparse uses a fixed 55 chars to print the help no matter the
                     # terminal size, abuse that to align the features
                     help="Enable developer features (comma-separated list, use   "
                          '"all" for access,reload,qweb,xml). Available features: '
                          "- access: log the traceback of access errors           "
                          "- qweb: log the compiled xml with qweb errors          "
                          "- reload: restart server on change in the source code  "
                          "- replica: simulate a deployment with readonly replica "
                          "- xml: read views from the source code, and not the db ")
    group.add_option("--stop", "--stop-after-init", action="store_true", dest="stop_after_init", my_default=False, file_exportable=False, file_loadable=False,
                     help="stop the server after its initialization")
    group.add_option("--osv-memory-count-limit", dest="osv_memory_count_limit", my_default=0,
                     help="Force a limit on the maximum number of records kept in the virtual "
                          "osv_memory tables. By default there is no limit.",
                     type="int")
    group.add_option("--transient-age-limit", dest="transient_age_limit", my_default=1.0,
                     help="Time limit (decimal value in hours) records created with a "
                          "TransientModel (mostly wizard) are kept in the database. Default to 1 hour.",
                     type="float")
    group.add_option("--max-cron-threads", dest="max_cron_threads", my_default=2,
                     help="Maximum number of threads processing concurrently cron jobs (default 2).",
                     type="int")
    group.add_option("--limit-time-worker-cron", dest="limit_time_worker_cron", my_default=0,
                     help="Maximum time a cron thread/worker stays alive before it is restarted. "
                          "Set to 0 to disable. (default: 0)",
                     type="int")
    group.add_option("--unaccent", dest="unaccent", my_default=False, action="store_true",
                     help="Try to enable the unaccent extension when creating new databases.")
    group.add_option("--geoip-city-db", "--geoip-db", dest="geoip_city_db", type='path', my_default='/usr/share/GeoIP/GeoLite2-City.mmdb',
                     help="Absolute path to the GeoIP City database file.")
    group.add_option("--geoip-country-db", dest="geoip_country_db", type='path', my_default='/usr/share/GeoIP/GeoLite2-Country.mmdb',
                     help="Absolute path to the GeoIP Country database file.")
    parser.add_option_group(group)

    group = optparse.OptionGroup(parser, "Multiprocessing options")
    # TODO sensible default for the three following limits.
    group.add_option(PosixOnlyOption(
                     "--workers", dest="workers", my_default=0,
                     help="Specify the number of workers, 0 disable prefork mode.",
                     type="int"))
    group.add_option(PosixOnlyOption(
                     "--gevent-workers", dest="gevent_workers", my_default=1,
                     help="Specify the number of gevent workers in prefork mode. (requires SO_REUSEPORT)",
                     type="int"))
    group.add_option("--limit-memory-soft", dest="limit_memory_soft", my_default=2048 * 1024 * 1024,
                     help="Maximum allowed virtual memory per worker (in bytes), when reached the worker be "
                     "reset after the current request (default 2048MiB).",
                     type="int")
    group.add_option(PosixOnlyOption(
                     "--limit-memory-soft-gevent", dest="limit_memory_soft_gevent", my_default=None,
                     help="Maximum allowed virtual memory per gevent worker (in bytes), when reached the worker will be "
                     "reset after the current request. Defaults to `--limit-memory-soft`.",
                     type="int"))
    group.add_option(PosixOnlyOption(
                     "--limit-memory-hard", dest="limit_memory_hard", my_default=2560 * 1024 * 1024,
                     help="Maximum allowed virtual memory per worker (in bytes), when reached, any memory "
                     "allocation will fail (default 2560MiB).",
                     type="int"))
    group.add_option(PosixOnlyOption(
                     "--limit-memory-hard-gevent", dest="limit_memory_hard_gevent", my_default=None,
                     help="Maximum allowed virtual memory per gevent worker (in bytes), when reached, any memory "
                     "allocation will fail. Defaults to `--limit-memory-hard`.",
                     type="int"))
    group.add_option(PosixOnlyOption(
                     "--limit-time-cpu", dest="limit_time_cpu", my_default=60,
                     help="Maximum allowed CPU time per request (default 60).",
                     type="int"))
    group.add_option("--limit-time-real", dest="limit_time_real", my_default=120,
                     help="Maximum allowed Real time per request (default 120).",
                     type="int")
    group.add_option("--limit-time-real-cron", dest="limit_time_real_cron", my_default=-1,
                     help="Maximum allowed Real time per cron job. (default: --limit-time-real). "
                          "Set to 0 for no limit. ",
                     type="int")
    group.add_option(PosixOnlyOption(
                     "--limit-request", dest="limit_request", my_default=2**16,
                     help="Maximum number of request to be processed per worker (default 65536).",
                     type="int"))
    parser.add_option_group(group)

    return parser


def _load_default_options(self):
    self._default_options.clear()
    self._default_options.update({
        option_name: option.my_default
        for option_name, option in self.options_index.items()
    })

    self._default_options['data_dir'] = (
        appdirs.user_data_dir(release.product_name, release.author)
        if os.path.isdir(os.path.expanduser('~')) else
        appdirs.site_data_dir(release.product_name, release.author)
        if sys.platform in ['win32', 'darwin'] else
        f'/var/lib/{release.product_name}'
    )

    default_config_dir = (
        appdirs.user_config_dir(release.product_name, release.author)
        if os.path.isdir(os.path.expanduser('~')) else
        appdirs.site_config_dir(release.product_name, release.author)
    )
    default_config_file = os.path.join(default_config_dir, 'odoo.conf')

    if os.path.isfile(default_config_file):
        rcfilepath = default_config_file
    elif os.name == 'nt':
        rcfilepath = os.path.join(os.path.abspath(os.path.dirname(sys.argv[0])), 'odoo.conf')
    elif os.path.isfile(rcfilepath := os.path.expanduser('~/.odoorc')):
        pass
    elif os.path.isfile(rcfilepath := os.path.expanduser('~/.openerp_serverrc')):
        self._warn("Since ages ago, the ~/.openerp_serverrc file has been replaced by ~/.odoorc", DeprecationWarning)
    else:
        rcfilepath = default_config_file
    self._default_options['config'] = self._normalize(rcfilepath)
