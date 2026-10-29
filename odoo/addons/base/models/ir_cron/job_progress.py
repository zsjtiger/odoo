# Part of Odoo. See LICENSE file for full copyright and licensing details.
"""The progress of the scheduled actions: the progress records, their commits and their rollbacks, and the notifications of the admins."""

from __future__ import annotations

import time
import typing

if typing.TYPE_CHECKING:
    pass

from .cron import _logger

def _notify_admin(self, message):
    """
        Notify ``message`` to some administrator.

        The base implementation of this method does nothing. It is
        supposed to be overridden with some actual communication
        mechanism.
        """
    _logger.warning(message)


def _add_progress(self, *, timed_out_counter=None):
    """
        Create a progress record for the given cron and add it to its
        context.

        :param int timed_out_counter: the number of times the cron has
            consecutively timed out
        :return: a pair ``(cron, progress)``, where the progress has
            been injected inside the cron's context
        """
    progress = self.env['ir.cron.progress'].sudo().create([{
        'cron_id': self.id,
        'remaining': 0,
        'done': 0,
        # we use timed_out_counter + 1 so that if the current execution
        # times out, the counter already takes it into account
        'timed_out_counter': 0 if timed_out_counter is None else timed_out_counter + 1,
    }])
    return self.with_context(ir_cron_progress_id=progress.id), progress


def _notify_progress(self, *, done: int, remaining: int, deactivate: bool = False):
    """
        Log the progress of the cron job.
        Use ``_commit_progress()`` instead.

        :param int done: the number of tasks already processed
        :param int remaining: the number of tasks left to process
        :param bool deactivate: whether the cron will be deactivated
        """
    if not (progress_id := self.env.context.get('ir_cron_progress_id')):
        return
    if done < 0 or remaining < 0:
        raise ValueError("`done` and `remaining` must be positive integers.")
    progress = self.env['ir.cron.progress'].sudo().browse(progress_id)
    assert progress.cron_id.id == self.env.context.get('cron_id'), "Progress on the wrong cron_id"
    progress.write({
        'remaining': remaining,
        'done': done,
        'deactivate': deactivate,
    })


def _commit_progress(
    self,
    processed: int = 0,
    *,
    remaining: int | None = None,
    deactivate: bool = False,
) -> float:
    """
        Commit and log progress for the batch from a cron function.

        The number of items processed is added to the current done count.
        If you don't specify a remaining count, the number of items processed
        is subtracted from the existing remaining count.

        If called from outside the cron job, the progress function call will
        just commit.

        :param processed: number of processed items in this step
        :param remaining: set the remaining count to the given count
        :param deactivate: deactivate the cron after running it
        :return: remaining time (seconds) for the cron run
        """
    # Typical use case:
    # https://www.odoo.com/documentation/latest/developer/reference/backend/actions.html#writing-cron-functions
    ctx = self.env.context
    progress = self.env['ir.cron.progress'].sudo().browse(ctx.get('ir_cron_progress_id'))
    if not progress:
        # not called during a cron, just commit
        self.env.cr.commit()
        return float('inf')
    assert processed >= 0, 'processed must be positive'
    assert (remaining or 0) >= 0, "remaining must be positive"
    assert progress.cron_id.id == ctx.get('cron_id'), "Progress on the wrong cron_id"
    if remaining is None:
        remaining = max(progress.remaining - processed, 0)
    done = progress.done + processed
    vals = {
        'remaining': remaining,
        'done': done,
    }
    if deactivate:
        vals['deactivate'] = True
    progress.write(vals)
    self.env.cr.commit()
    return max(ctx.get('cron_end_time', float('inf')) - time.monotonic(), 0)


def _rollback_progress(self) -> None:
    """The rollback with the same logic as the commit for cron jobs."""
    self.env.cr.rollback()
