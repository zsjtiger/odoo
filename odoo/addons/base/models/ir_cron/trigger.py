"""The triggers of the scheduled actions (ir.cron.trigger)."""

from __future__ import annotations

import typing
from datetime import datetime
from dateutil.relativedelta import relativedelta
from odoo import api, fields, models
from odoo.tools.constants import GC_UNLINK_LIMIT

if typing.TYPE_CHECKING:
    pass


class IrCronTrigger(models.Model):
    _name = 'ir.cron.trigger'
    _description = 'Triggered Action'
    _rec_name = 'cron_id'
    _allow_sudo_commands = False

    cron_id = fields.Many2one("ir.cron", index=True, required=True, ondelete="cascade")
    call_at = fields.Datetime(index=True, required=True)

    @api.autovacuum
    def _gc_cron_triggers(self):
        # active cron jobs are cleared by `_clear_schedule` when the job starts
        domain = [
            ('call_at', '<', datetime.now() + relativedelta(weeks=-1)),
            ('cron_id.active', '=', False),
        ]
        records = self.search(domain, limit=GC_UNLINK_LIMIT)
        records.unlink()
        return len(records), len(records) == GC_UNLINK_LIMIT  # done, remaining
