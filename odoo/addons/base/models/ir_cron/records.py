# Part of Odoo. See LICENSE file for full copyright and licensing details.
"""The records of the scheduled actions: the names, the creation and the writes, and the actions that open them."""

from __future__ import annotations

import os
import typing
from odoo.exceptions import LockError, UserError

if typing.TYPE_CHECKING:
    pass

from .cron import IrCron

def _compute_cron_name(self):
    for cron in self.with_context(lang='en_US'):
        cron.cron_name = cron.ir_actions_server_id.name


def create(self, vals_list):
    for vals in vals_list:
        vals['usage'] = 'ir_cron'
    if os.getenv('ODOO_NOTIFY_CRON_CHANGES'):
        self.env.cr.postcommit.add(self._notifydb)
    return super(IrCron, self).create(vals_list)


def default_get(self, fields):
    # only 'code' state is supported for cron job so set it as default
    model = self
    if not model.env.context.get('default_state'):
        model = model.with_context(default_state='code')
    return super(IrCron, model).default_get(fields)


def write(self, vals):
    try:
        self.lock_for_update(allow_referencing=True)
    except LockError:
        raise UserError(self.env._(
            "Record cannot be modified right now: "
            "This cron task is currently being executed and may not be modified "
            "Please try again in a few minutes"
        )) from None
    if ('nextcall' in vals or vals.get('active')) and os.getenv('ODOO_NOTIFY_CRON_CHANGES'):
        self.env.cr.postcommit.add(self._notifydb)
    return super(IrCron, self).write(vals)


def _unlink_unless_running(self):
    try:
        self.lock_for_update()
    except LockError:
        raise UserError(self.env._(
            "Record cannot be modified right now: "
            "This cron task is currently being executed and may not be modified "
            "Please try again in a few minutes"
        )) from None


def action_open_parent_action(self):
    return self.ir_actions_server_id.action_open_parent_action()


def action_open_scheduled_action(self):
    return self.ir_actions_server_id.action_open_scheduled_action()
