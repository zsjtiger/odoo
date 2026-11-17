"""The progress of the scheduled actions (ir.cron.progress)."""

from __future__ import annotations

import typing
from datetime import datetime
from dateutil.relativedelta import relativedelta
from odoo import api, fields, models
from odoo.tools.constants import GC_UNLINK_LIMIT

if typing.TYPE_CHECKING:
    pass


class IrCronProgress(models.Model):
    _name = 'ir.cron.progress'
    _description = 'Progress of Scheduled Action'
    _rec_name = 'cron_id'

    cron_id = fields.Many2one("ir.cron", required=True, index=True, ondelete='cascade')
    remaining = fields.Integer(default=0)
    done = fields.Integer(default=0)
    deactivate = fields.Boolean()
    timed_out_counter = fields.Integer(default=0)

    @api.autovacuum
    def _gc_cron_progress(self):
        records = self.search([('create_date', '<', datetime.now() - relativedelta(weeks=1))], limit=GC_UNLINK_LIMIT)
        records.unlink()
        return len(records), len(records) == GC_UNLINK_LIMIT  # done, remaining
