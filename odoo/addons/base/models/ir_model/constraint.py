"""The constraints of the models (ir.model.constraint)."""

from __future__ import annotations

import logging
from psycopg2.extras import Json
from odoo import fields, models
from odoo.tools import sql, SQL


_logger = logging.getLogger('odoo.addons.base.models.ir_model')


class IrModelConstraint(models.Model):
    """
    This model tracks PostgreSQL indexes, foreign keys and constraints
    used by Odoo models.
    """
    _name = 'ir.model.constraint'
    _description = 'Model Constraint'
    _allow_sudo_commands = False

    name = fields.Char(
        string='Constraint', required=True, index=True, readonly=True,
        copy=lambda c: f'{c.name}_name',
        help="PostgreSQL constraint or foreign key name.")
    definition = fields.Char(help="PostgreSQL constraint definition", readonly=True)
    message = fields.Char(help="Error message returned when the constraint is violated.", translate=True)
    model = fields.Many2one('ir.model', required=True, ondelete="cascade", index=True, readonly=True)
    module = fields.Many2one('ir.module.module', required=True, index=True, ondelete='cascade', readonly=True)
    type = fields.Char(
        string='Constraint Type', required=True, size=1, readonly=True,
        help="Type of the constraint: `f` for a foreign key, `u` for other constraints.")

    _module_name_uniq = models.Constraint('UNIQUE (name, module)',
        'Constraints with the same name are unique per module.')

    def unlink(self):
        self.check_access('unlink')
        ids_set = set(self.ids)
        for data in self.sorted(key='id', reverse=True):
            name = data.name
            if data.model.model in self.env:
                table = self.env[data.model.model]._table
            else:
                table = data.model.model.replace('.', '_')

            # double-check we are really going to delete all the owners of this schema element
            external_ids = {
                id_ for [id_] in self.env.execute_query(SQL(
                    """SELECT id from ir_model_constraint where name=%s""", name
                ))
            }
            if external_ids - ids_set:
                # as installed modules have defined this element we must not delete it!
                continue

            typ = data.type
            if typ in ('f', 'u'):
                # test if FK exists on this table
                # Since type='u' means any "other" constraint, to avoid issues we limit to
                # 'c' -> check, 'u' -> unique, 'x' -> exclude constraints, effective leaving
                # out 'p' -> primary key and 'f' -> foreign key, constraints.
                # For 'f', it could be on a related m2m table, in which case we ignore it.
                # See: https://www.postgresql.org/docs/9.5/catalog-pg-constraint.html
                hname = sql.make_identifier(name)
                if self.env.execute_query(SQL(
                    """SELECT
                    FROM pg_constraint cs
                    JOIN pg_class cl
                    ON (cs.conrelid = cl.oid)
                    WHERE cs.contype IN %s AND cs.conname = %s AND cl.relname = %s
                    AND cl.relnamespace = current_schema::regnamespace
                    """, ('c', 'u', 'x') if typ == 'u' else (typ,), hname, table
                )):
                    self.env.execute_query(SQL(
                        'ALTER TABLE %s DROP CONSTRAINT %s',
                        SQL.identifier(table),
                        SQL.identifier(hname),
                    ))
                    _logger.info('Dropped CONSTRAINT %s@%s', name, data.model.model)

            if typ == 'i':
                hname = sql.make_identifier(name)
                # drop index if it exists
                self.env.execute_query(SQL("DROP INDEX IF EXISTS %s", SQL.identifier(hname)))
                _logger.info('Dropped INDEX %s@%s', name, data.model.model)

        return super().unlink()

    def _reflect_constraint(self, model, conname, type, definition, module, message=None):
        """ Reflect the given constraint, and return its corresponding record.
            The reflection makes it possible to remove a constraint when its
            corresponding module is uninstalled. ``type`` is either 'f', 'i', or 'u'
            depending on the constraint being a foreign key or not.
        """
        if not module:
            # no need to save constraints for custom models as they're not part
            # of any module
            return
        assert type in ('f', 'u', 'i')
        rows = self.env.execute_query_dict(SQL(
            """SELECT c.id, type, definition, message->'en_US' as message
            FROM ir_model_constraint c, ir_module_module m
            WHERE c.module = m.id AND c.name = %s AND m.name = %s
            """, conname, module
        ))
        if not rows:
            [[cons_id]] = self.env.execute_query(SQL(
                """
                INSERT INTO ir_model_constraint
                    (name, create_date, write_date, create_uid, write_uid, module, model, type, definition, message)
                VALUES (%s,
                        now() AT TIME ZONE 'UTC',
                        now() AT TIME ZONE 'UTC',
                        %s, %s,
                        (SELECT id FROM ir_module_module WHERE name=%s),
                        (SELECT id FROM ir_model WHERE model=%s),
                        %s, %s, %s)
                RETURNING id
                """, conname, self.env.uid, self.env.uid, module, model._name, type, definition, Json({'en_US': message})
            ))
            return self.browse(cons_id)
        [cons] = rows
        cons_id = cons.pop('id')
        if cons != dict(type=type, definition=definition, message=message):
            self.env.execute_query(SQL(
                """
                UPDATE ir_model_constraint
                SET write_date=now() AT TIME ZONE 'UTC',
                    write_uid = %s, type = %s, definition = %s, message = %s
                WHERE id = %s""",
                self.env.uid, type, definition, Json({'en_US': message}), cons_id
            ))
        return self.browse(cons_id)

    def _reflect_constraints(self, model_names):
        """ Reflect the table objects of the given models. """
        data_list = []
        for model_name in model_names:
            data_list.extend(self._reflect_table_object(self.env[model_name]))
        self.env['ir.model.data']._update_xmlids(data_list)

    def _reflect_table_object(self, model):
        """ Reflect the _table_objects of the given model. """
        data_list = []
        for conname, cons in model._table_objects.items():
            module = cons._module
            if not conname or not module:
                _logger.warning("Missing module or constraint name for %s", cons)
                continue
            definition = cons.get_definition(model.pool)
            message = cons.message
            if not isinstance(message, str) or not message:
                message = None
            typ = 'i' if isinstance(cons, models.Index) else 'u'
            record = self._reflect_constraint(model, conname, typ, definition, module, message)
            xml_id = '%s.constraint_%s' % (module, conname)
            if record:
                data_list.append(dict(xml_id=xml_id, record=record))
        return data_list
