"""Initialization of the databases: the schema of the modules, the categories and the timezones."""

from __future__ import annotations

import collections
import contextlib
import functools
import logging
import os
import pathlib
import typing
from contextlib import closing
from importlib import resources
from zoneinfo import TZPATH
from psycopg2.extras import Json
import odoo.api
import odoo.modules
import odoo.modules.neutralize
import odoo.release
import odoo.orm.database.sql_db
import odoo.tools
from odoo.tools import config
from odoo.tools.date_utils import all_timezones

if typing.TYPE_CHECKING:
    from odoo.orm.database.sql_db import Cursor


_logger = logging.getLogger('odoo.modules.db')


RANDOM_SERIAL = any(map(os.getenv, ('ODOO_RUNBOT', 'ODOO_TEST')))


def initialize(cr: Cursor) -> None:
    """ Initialize a database with for the ORM.

    This executes base/data/base_data.sql, creates the ir_module_categories
    (taken from each module descriptor file), and creates the ir_module_module
    and ir_model_data entries.

    """
    try:
        with odoo.tools.misc.file_open('base/data/base_data.sql') as base_sql_file:
            cr.execute(base_sql_file.read())  # pylint: disable=sql-injection
    except FileNotFoundError:
        m = "File not found: 'base.sql' (provided by module 'base')."
        _logger.critical(m)
        raise OSError(m)
    if RANDOM_SERIAL:
        _logger.info("Initializing tables with random ids")
        with odoo.tools.misc.file_open('base/data/base_data_test.sql') as base_sql_file:
            cr.execute(base_sql_file.read())  # pylint: disable=sql-injection

    categories_memo = {}
    for info in odoo.modules.Manifest.all_addon_manifests():
        module_name = info.name
        categories = info['category'].split('/')
        category_id = create_categories(cr, categories, categories_memo)

        if info['installable']:
            state = 'uninstalled'
        else:
            state = 'uninstallable'

        cr.execute('INSERT INTO ir_module_module \
                (author, website, name, shortdesc, description, \
                    category_id, auto_install, state, web, license, application, icon, sequence, summary) \
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id', (
            info['author'],
            info['website'], module_name, Json({'en_US': info['name']}),
            Json({'en_US': info['description']}), category_id,
            info['auto_install'] is not False, state,
            info['web'],
            info['license'],
            info['application'], info['icon'],
            info['sequence'], Json({'en_US': info['summary']})))
        row = cr.fetchone()
        assert row is not None  # for typing
        module_id = row[0]
        cr.execute(
            'INSERT INTO ir_model_data'
            '(name,model,module, res_id, noupdate) VALUES (%s,%s,%s,%s,%s)',
            ('module_' + module_name, 'ir.module.module', 'base', module_id, True),
        )
        dependencies = info['depends']
        for d in dependencies:
            cr.execute(
                'INSERT INTO ir_module_module_dependency (module_id, name, auto_install_required)'
                ' VALUES (%s, %s, %s)',
                (module_id, d, d in (info['auto_install'] or ())),
            )

    if config.get('skip_auto_install'):
        # even if skip_auto_install is enabled we still want to have base
        cr.execute("""UPDATE ir_module_module SET state='to install' WHERE name = 'base'""")
        return

    # Install recursively all auto-installing modules
    while True:
        # this selects all the auto_install modules whose auto_install_required
        # deps are marked as to install
        cr.execute("""
        SELECT m.name FROM ir_module_module m
        WHERE m.auto_install
        AND state not in ('to install', 'uninstallable')
        AND NOT EXISTS (
            SELECT 1 FROM ir_module_module_dependency d
            LEFT JOIN ir_module_module mdep ON (d.name = mdep.name)
            WHERE d.module_id = m.id
              AND (
                  mdep.id IS NULL
                  OR (d.auto_install_required AND mdep.state != 'to install')
              )
        )""")
        to_auto_install = [x[0] for x in cr.fetchall()]
        # however if the module has non-required deps we need to install
        # those, so merge-in the modules which have a dependen*t* which is
        # *either* to_install or in to_auto_install and merge it in?
        cr.execute("""
        SELECT d.name FROM ir_module_module_dependency d
        JOIN ir_module_module m ON (d.module_id = m.id)
        JOIN ir_module_module mdep ON (d.name = mdep.name)
        WHERE (m.state = 'to install' OR m.name = any(%s))
            -- don't re-mark marked modules
        AND NOT (mdep.state = 'to install' OR mdep.name = any(%s))
        """, [to_auto_install, to_auto_install])
        to_auto_install.extend(x[0] for x in cr.fetchall())

        if not to_auto_install:
            break
        cr.execute("""UPDATE ir_module_module SET state='to install' WHERE name in %s""", (tuple(to_auto_install),))


def create_categories(cr: Cursor, categories: list[str], memo: dict | None = None) -> int | None:
    """ Create the ir_module_category entries for some categories.

    categories is a list of strings forming a single category with its
    parent categories, like ['Grand Parent', 'Parent', 'Child'].

    Return the database id of the (last) category.

    """
    p_id = None
    xml_id = 'module_category'
    if memo is None:
        memo = {}
    for category in categories:
        xml_id += '_' + category.lower().replace('&', 'and').replace(' ', '_')
        if category_id := memo.get(xml_id):
            p_id = category_id
            continue

        # search via xml_id (because some categories are renamed)
        cr.execute("SELECT res_id FROM ir_model_data WHERE name=%s AND module=%s AND model=%s",
                   (xml_id, "base", "ir.module.category"))
        row = cr.fetchone()
        if not row:
            cr.execute('INSERT INTO ir_module_category \
                    (name, parent_id) \
                    VALUES (%s, %s) RETURNING id', (Json({'en_US': category}), p_id))
            row = cr.fetchone()
            assert row is not None  # for typing
            p_id = row[0]
            cr.execute('INSERT INTO ir_model_data (module, name, res_id, model, noupdate) \
                       VALUES (%s, %s, %s, %s, %s)', ('base', xml_id, p_id, 'ir.module.category', True))
        else:
            p_id = row[0]
        assert isinstance(p_id, int)
        memo[xml_id] = p_id
    return p_id


@functools.cache
def country_timezones():
    """Ported from pytz on top of zoneinfo: the mapping of country code is
    available in tzdb's zone.tab (and in a more complex / complete form in
    zone1970.tab but we ignore that), following the example of zoneinfo we first
    check for it in tzdata and fall back on the OS's zoneinfo db.
    """
    zonemap = collections.defaultdict(list)

    tzpath = []
    with contextlib.suppress(ModuleNotFoundError):
        tzpath = [resources.files('tzdata').joinpath('zoneinfo')]
    tzpath.extend(map(pathlib.Path, TZPATH))

    for p in tzpath:
        try:
            zone_file = p.joinpath('zone.tab').open('r', encoding='ascii')
        except FileNotFoundError:
            continue

        with zone_file:
            for line in zone_file:
                if line.startswith('#'):
                    continue
                code, _coordinates, zone = line.split(None, 4)[:3]
                if zone not in all_timezones:
                    continue
                zonemap[code].append(zone)
            break

    return dict(zonemap)


def _initialize_db(
    db_name: str,
    *,
    demo: bool,
    user_login: str = 'admin',
    user_password: str,
    lang: str,
    country_code: str | None = None,
    phone: str | None = None,
) -> None:
    """
    Initialize a new registry for ``db_name``, installing the necessary
    base modules and the records for the provided arguments.
    """
    odoo.tools.config['load_language'] = lang

    registry = odoo.modules.registry.Registry.new(db_name, update_module=True, new_db_demo=demo)

    with closing(registry.cursor()) as cr:
        env = odoo.api.Environment(cr, odoo.api.SUPERUSER_ID, {})

        if lang:
            modules = env['ir.module.module'].search([('state', '=', 'installed')])
            modules._update_translations(lang)

            main_company_values = {}
            if country_code:
                country = env['res.country'].search([('code', 'ilike', country_code)], limit=1)
                main_company_values = {'country_id': country.id, 'currency_id': country.currency_id.id}
                if len(ct := country_timezones().get(country.code, [])) == 1:
                    env['res.users'].search([]).write({'tz': ct[0]})
            if phone:
                main_company_values['phone'] = phone
            if '@' in user_login:
                main_company_values['email'] = user_login
            if main_company_values:
                env.ref('base.main_company').write(main_company_values)

        # update admin's password and lang and login
        values = {'password': user_password, 'lang': lang}
        if user_login:
            values['login'] = user_login
            emails = odoo.tools.email_split(user_login)
            if emails:
                values['email'] = emails[0]
        env.ref('base.user_admin').write(values)

        cr.commit()
