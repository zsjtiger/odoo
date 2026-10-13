# Part of Odoo. See LICENSE file for full copyright and licensing details.
"""The scheduled actions (ir.cron): the model and its entry points. The methods are split by concern in the other modules of this package."""

from __future__ import annotations

import logging
import typing
from datetime import datetime
from odoo import api, fields, models
from odoo.tools import SQL
from odoo.tools.func import deprecated
from .helpers import CompletionStatus

if typing.TYPE_CHECKING:
    from collections.abc import Iterable
    from odoo.sql_db import BaseCursor


class IrCron(models.Model):
    """ Model describing cron jobs (also called actions or tasks).
    """
    _name = 'ir.cron'
    _order = 'cron_name, id'
    _description = 'Scheduled Action'
    _allow_sudo_commands = False
    _inherits = {'ir.actions.server': 'ir_actions_server_id'}
    ir_actions_server_id = fields.Many2one(
        'ir.actions.server', 'Server action', index=True,
        delegate=True, ondelete='restrict', required=True)
    cron_name = fields.Char('Name', compute='_compute_cron_name', store=True)
    user_id = fields.Many2one('res.users', string='Scheduler User', default=lambda self: self.env.user, required=True)
    active = fields.Boolean(default=True)
    interval_number = fields.Integer(default=1, help="Repeat every x.", required=True, aggregator='avg')
    interval_type = fields.Selection([('minutes', 'Minutes'),
                                      ('hours', 'Hours'),
                                      ('days', 'Days'),
                                      ('weeks', 'Weeks'),
                                      ('months', 'Months')], string='Interval Unit', default='months', required=True)
    nextcall = fields.Datetime(string='Next Execution Date', required=True, default=fields.Datetime.now, help="Next planned execution date for this job.")
    lastcall = fields.Datetime(string='Last Execution Date', help="Previous time the cron ran successfully, provided to the job through the context on the `lastcall` key")
    priority = fields.Integer(default=5, aggregator=None, help='The priority of the job, as an integer: 0 means higher priority, 10 means lower priority.')
    failure_count = fields.Integer(default=0, help="The number of consecutive failures of this job. It is automatically reset on success.")
    first_failure_date = fields.Datetime(string='First Failure Date', help="The first time the cron failed. It is automatically reset on success.")
    _check_strictly_positive_interval = models.Constraint(
        'CHECK(interval_number > 0)',
        "The interval number must be a strictly positive number.",
    )
    @api.depends('ir_actions_server_id.name')
    def _compute_cron_name(self):
        return _records._compute_cron_name(self)
    @api.model_create_multi
    def create(self, vals_list):
        return _records.create(self, vals_list)
    @api.model
    def default_get(self, fields):
        return _records.default_get(self, fields)
    def method_direct_trigger(self):
        return _jobs.method_direct_trigger(self)
    @staticmethod
    def _process_jobs(db_name: str) -> None:
        return _jobs._process_jobs(db_name)
    @staticmethod
    def _process_jobs_loop(cron_cr: BaseCursor, *, job_ids: Iterable[int]=()):
        return _jobs._process_jobs_loop(cron_cr, job_ids=job_ids)
    @staticmethod
    def _check_version(cron_cr):
        return _jobs._check_version(cron_cr)
    @staticmethod
    def _check_modules_state(cr, jobs):
        return _jobs._check_modules_state(cr, jobs)
    @staticmethod
    def _get_ready_sql_condition(cr: BaseCursor) -> SQL:
        return _jobs._get_ready_sql_condition(cr)
    @staticmethod
    def _get_all_ready_jobs(cr: BaseCursor) -> list[dict]:
        return _jobs._get_all_ready_jobs(cr)
    @staticmethod
    def _acquire_one_job(cr: BaseCursor, job_id: int, *, include_not_ready: bool=False) -> dict | None:
        return _jobs._acquire_one_job(cr, job_id, include_not_ready=include_not_ready)
    def _notify_admin(self, message):
        return _job_progress._notify_admin(self, message)
    @classmethod
    def _process_job(cls, cron_cr: BaseCursor, job) -> None:
        return _jobs._process_job(cls, cron_cr, job)
    @classmethod
    def _run_job(cls, job) -> CompletionStatus:
        return _jobs._run_job(cls, job)
    @api.model
    def _update_failure_count(self, job: dict, status: CompletionStatus) -> None:
        return _schedule._update_failure_count(self, job, status)
    @api.model
    def _clear_schedule(self, job):
        return _schedule._clear_schedule(self, job)
    @api.model
    def _reschedule_later(self, job: dict) -> None:
        return _schedule._reschedule_later(self, job)
    @api.model
    def _reschedule_asap(self, job: dict) -> None:
        return _schedule._reschedule_asap(self, job)
    def _callback(self, cron_name, server_action_id):
        return _schedule._callback(self, cron_name, server_action_id)
    def write(self, vals):
        return _records.write(self, vals)
    @api.ondelete(at_uninstall=False)
    def _unlink_unless_running(self):
        return _records._unlink_unless_running(self)
    @api.model
    def toggle(self, model, domain):
        return _schedule.toggle(self, model, domain)
    def _trigger(self, at: datetime | Iterable[datetime] | None=None, *, coalesce: int=0):
        return _schedule._trigger(self, at, coalesce=coalesce)
    def _trigger_list(self, at_list: list[datetime]):
        return _schedule._trigger_list(self, at_list)
    @api.model
    def _notifydb(self):
        return _schedule._notifydb(self)
    def _add_progress(self, *, timed_out_counter=None):
        return _job_progress._add_progress(self, timed_out_counter=timed_out_counter)
    @deprecated('Since 19.0, use _commit_progress')
    def _notify_progress(self, *, done: int, remaining: int, deactivate: bool=False):
        return _job_progress._notify_progress(self, done=done, remaining=remaining, deactivate=deactivate)
    @api.model
    def _commit_progress(self, processed: int=0, *, remaining: int | None=None, deactivate: bool=False) -> float:
        return _job_progress._commit_progress(self, processed, remaining=remaining, deactivate=deactivate)
    @api.model
    def _rollback_progress(self) -> None:
        return _job_progress._rollback_progress(self)
    def action_open_parent_action(self):
        return _records.action_open_parent_action(self)
    def action_open_scheduled_action(self):
        return _records.action_open_scheduled_action(self)


_logger = logging.getLogger('odoo.addons.base.models.ir_cron')


# the delegated methods of the class, and the modules that use the class: at the end, they import this module
from . import jobs as _jobs, schedule as _schedule, job_progress as _job_progress, records as _records  # noqa: E402
