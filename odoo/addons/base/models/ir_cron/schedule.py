# Part of Odoo. See LICENSE file for full copyright and licensing details.
"""The schedule of the scheduled actions: the failure counts, the rescheduling, the triggers and the notifications of the database."""

from __future__ import annotations

import logging
import math
import os
import typing
from datetime import datetime, timezone
from odoo import fields, sql_db
from odoo.exceptions import LockError
from odoo.tools import SQL, config
from .helpers import CompletionStatus, MIN_DELTA_BEFORE_DEACTIVATION, MIN_FAILURE_COUNT_BEFORE_DEACTIVATION, ODOO_NOTIFY_FUNCTION, _intervalTypes

if typing.TYPE_CHECKING:
    from collections.abc import Iterable

from .cron import _logger

def _update_failure_count(self, job: dict, status: CompletionStatus) -> None:
    """
        Update cron ``failure_count`` and ``first_failure_date`` given
        the job's completion status. Deactivate the cron when BOTH the
        counter reaches ``MIN_FAILURE_COUNT_BEFORE_DEACTIVATION`` AND
        the time delta reaches ``MIN_DELTA_BEFORE_DEACTIVATION``.

        On ``'fully done'`` and ``'partially done'``, the counter and
        failure date are reset.

        On ``'failed'`` the counter is increased and the first failure
        date is set if the counter was 0. In case both thresholds are
        reached, ``active`` is set to ``False`` and both values are
        reset.
        """
    if status == CompletionStatus.FAILED:
        now = self.env.cr.now().replace(microsecond=0)
        failure_count = job['failure_count'] + 1
        first_failure_date = job['first_failure_date'] or now
        active = job['active']
        if (
            failure_count >= MIN_FAILURE_COUNT_BEFORE_DEACTIVATION
            and first_failure_date + MIN_DELTA_BEFORE_DEACTIVATION < now
        ):
            failure_count = 0
            first_failure_date = None
            active = False
            self._notify_admin(self.env._(
                "Cron job %(name)s (%(id)s) has been deactivated after failing %(count)s times. "
                "More information can be found in the server logs around %(time)s.",
                name=repr(job['cron_name']),
                id=job['id'],
                count=MIN_FAILURE_COUNT_BEFORE_DEACTIVATION,
                time=now,
            ))
        elif (
            # the minimum time has passed, and the fail count is low
            first_failure_date + MIN_DELTA_BEFORE_DEACTIVATION < now
            and MIN_FAILURE_COUNT_BEFORE_DEACTIVATION // 2 <= failure_count <= MIN_FAILURE_COUNT_BEFORE_DEACTIVATION
        ) or (
            # we fail often but we have some time before deactivation
            failure_count > MIN_FAILURE_COUNT_BEFORE_DEACTIVATION
            and first_failure_date + MIN_DELTA_BEFORE_DEACTIVATION / 2 < now
            # throttle: number with 1 digit followed only by 0's
            and len(str(failure_count).rstrip('0')) == 1
        ):
            self._notify_admin(self.env._(
                "Cron job %(name)s (%(id)s) is failing and will be deactivated if you don't take action. "
                "More information can be found in the server logs around %(time)s.",
                name=repr(job['cron_name']),
                id=job['id'],
                time=now,
            ))
    else:
        failure_count = 0
        first_failure_date = None
        active = job['active']

    self.env.cr.execute("""
            UPDATE ir_cron
            SET failure_count = %s,
                first_failure_date = %s,
                active = %s
            WHERE id = %s
        """, [
        failure_count,
        first_failure_date,
        active,
        job['id'],
    ])


def _clear_schedule(self, job):
    """Remove triggers for the given job."""
    now = self.env.cr.now().replace(microsecond=0)
    self.env.cr.execute("""
            DELETE FROM ir_cron_trigger
            WHERE cron_id = %s
              AND call_at <= %s
        """, [job['id'], now])


def _reschedule_later(self, job: dict) -> None:
    """
        Reschedule the job to be executed later, after its regular
        interval or upon a trigger.
        """
    now = self.env.cr.now().replace(microsecond=0)
    nextcall = job['nextcall']
    # Use the timezone of the user when adding the interval. When adding a
    # day or more, the user may want to keep the same hour each day.
    # The interval won't be fixed, but the hour will stay the same,
    # even when changing DST.
    interval = _intervalTypes[job['interval_type']](job['interval_number'])
    while nextcall <= now:
        nextcall = fields.Datetime.context_timestamp(self, nextcall)
        nextcall += interval
        nextcall = nextcall.astimezone(timezone.utc).replace(tzinfo=None)

    self.env.cr.execute("""
            UPDATE ir_cron
            SET nextcall = %s,
                lastcall = %s
            WHERE id = %s
        """, [nextcall, now, job['id']])


def _reschedule_asap(self, job: dict) -> None:
    """
        Reschedule the job to be executed ASAP, after the other cron
        jobs had a chance to run.
        """
    now = self.env.cr.now().replace(microsecond=0)
    self.env.cr.execute("""
            INSERT INTO ir_cron_trigger(call_at, cron_id)
            VALUES (%s, %s)
        """, [now, job['id']])


def _callback(self, cron_name, server_action_id):
    """ Run the method associated to a given job. It takes care of logging
        and exception handling. Note that the user running the server action
        is the user calling this method. """
    self.ensure_one()
    try:
        _logger.debug(
            "cron.object.execute(%r, %d, '*', %r, %d)",
            self.env.cr.dbname,
            self.env.uid,
            cron_name,
            server_action_id,
        )
        self.env['ir.actions.server'].browse(server_action_id).run()
        self.env.flush_all()
        self.env.cr.commit()
    except Exception:
        self.env.cr.rollback()
        raise


def toggle(self, model, domain):
    # Prevent deactivated cron jobs from being re-enabled through side effects on
    # neutralized databases.
    if self.env['ir.config_parameter'].sudo().get_bool('database.is_neutralized'):
        return True

    active = bool(self.env[model].search_count(domain))
    try:
        self.lock_for_update(allow_referencing=True)
    except LockError:
        return True
    return self.write({'active': active})


def _trigger(self, at: datetime | Iterable[datetime] | None = None, *, coalesce: int = 0):
    """
        Schedule a cron job to be executed soon independently of its
        ``nextcall`` field value.

        By default, the cron is scheduled to be executed the next time
        the cron worker wakes up, but the optional `at` argument may be
        given to delay the execution later, with a precision down to 1
        minute.

        The method may be called with a datetime or an iterable of
        datetime. The actual implementation is in :meth:`~._trigger_list`,
        which is the recommended method for overrides.

        :param at:
            When to execute the cron, at one or several moments in time
            instead of as soon as possible.
        :param coalesce: coalescing window, in minutes, every trigger
            is shifted to the end of the window, this allows limiting
            the number or frequency of wakeups for less pressing triggers
        :return: the created triggers records
        """
    if at is None:
        at_list = [fields.Datetime.now()]
    elif isinstance(at, datetime):
        at_list = [at]
    else:
        at_list = list(at)
        assert all(isinstance(at, datetime) for at in at_list)

    if coalesce:
        factor = coalesce * 60
        at_list = [
            datetime.fromtimestamp(
                math.ceil(dt.timestamp() / factor) * factor,
            )
            for dt in at_list
        ]
    return self._trigger_list(at_list)


def _trigger_list(self, at_list: list[datetime]):
    """
        Implementation of :meth:`~._trigger`.

        :param at_list: Execute the cron later, at precise moments in time.
        :return: the created triggers records
        """
    self.ensure_one()
    now = fields.Datetime.now()

    if not self.sudo().active:
        # skip triggers that would be ignored
        at_list = [at for at in at_list if at > now]

    if not at_list:
        return self.env['ir.cron.trigger']

    triggers = self.env['ir.cron.trigger'].sudo().create([
        {'cron_id': self.id, 'call_at': at}
        for at in at_list
    ])
    if _logger.isEnabledFor(logging.DEBUG):
        ats = ', '.join(map(str, at_list))
        _logger.debug('Job %r (%s) will execute at %s', self.sudo().name, self.id, ats)

    if min(at_list) <= now or os.getenv('ODOO_NOTIFY_CRON_CHANGES'):
        self.env.cr.postcommit.add(self._notifydb)
    return triggers


def _notifydb(self):
    """ Wake up the cron workers
        The ODOO_NOTIFY_CRON_CHANGES environment variable allows to force the notifydb on both
        IrCron modification and on trigger creation (regardless of call_at)
        """
    with sql_db.db_connect(config['db_system']).cursor() as cr:
        cr.execute(SQL("SELECT %s('cron_trigger', %s)", SQL.identifier(ODOO_NOTIFY_FUNCTION), self.env.cr.dbname))
    _logger.debug("cron workers notified")
