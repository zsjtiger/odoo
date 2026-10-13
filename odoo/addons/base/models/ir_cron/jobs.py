# Part of Odoo. See LICENSE file for full copyright and licensing details.
"""The execution of the scheduled actions: the jobs, their acquisition, their run and the checks before running them."""

from __future__ import annotations

import contextvars
import logging
import os
import threading
import time
import typing
from datetime import datetime
import psycopg2
import psycopg2.errors
from odoo import api, sql_db
from odoo.exceptions import UserError
from odoo.http.dispatcher import serialize_exception
from odoo.tools import SQL
from .helpers import BASE_VERSION, BadModuleState, BadVersion, CONSECUTIVE_TIMEOUT_FOR_FAILURE, CompletionStatus, ListLogHandler, MAX_FAIL_TIME, MIN_RUNS_PER_JOB, MIN_TIME_PER_JOB

if typing.TYPE_CHECKING:
    from collections.abc import Iterable
    from odoo.sql_db import BaseCursor

from .cron import IrCron, _logger

def method_direct_trigger(self):
    """Run the CRON job in the current (HTTP) thread.

        The job is still ran as it would be by the scheduler: a new cursor
        is used for the execution of the job.

        :raises UserError: when the job is already running
        """
    self.ensure_one()
    self.browse().check_access('write')
    # cron will be run in a separate transaction, flush before and
    # invalidate because data will be changed by that transaction
    self.env.invalidate_all(flush=True)
    cron_cr = self.env.cr
    job = self._acquire_one_job(cron_cr, self.id, include_not_ready=True)
    if not job:
        raise UserError(self.env._("Job '%s' already executing", self.name))

    with ListLogHandler(_logger, logging.ERROR) as capture:
        self._process_job(cron_cr, job)
    if log_record := next((lr for lr in capture if getattr(lr, 'exc_info', None)), None):
        _exc_type, exception, _traceback = log_record.exc_info
        e = RuntimeError()
        e.__cause__ = exception
        error = {
            'code': 0,  # we don't care of this code
            'message': "Odoo Server Error",
            'data': serialize_exception(e),
        }
        return {
            'type': 'ir.actions.client',
            'tag': 'display_exception',
            'params': error,
        }
    return True


def _process_jobs(db_name: str) -> None:
    """ Execute every job ready to be run on this database. """
    try:
        db = sql_db.db_connect(db_name)
        threading.current_thread().dbname = db_name
        with db.cursor() as cron_cr:
            cls = IrCron
            cls._check_version(cron_cr)
            jobs = cls._get_all_ready_jobs(cron_cr)
            if not jobs:
                return
            cls._check_modules_state(cron_cr, jobs)
            cls._process_jobs_loop(cron_cr, job_ids=[job['id'] for job in jobs])
    except BadVersion:
        _logger.warning('Skipping database %s as its base version is not %s.', db_name, BASE_VERSION)
    except BadModuleState:
        _logger.warning('Skipping database %s because of modules to install/upgrade/remove.', db_name)
    except psycopg2.errors.UndefinedTable:
        # The table ir_cron does not exist; this is probably not an OpenERP database.
        _logger.warning('Tried to poll an undefined table on database %s.', db_name)
    except psycopg2.ProgrammingError:
        raise
    except Exception:
        _logger.warning('Exception in cron:', exc_info=True)
    finally:
        if hasattr(threading.current_thread(), 'dbname'):
            del threading.current_thread().dbname


def _process_jobs_loop(cron_cr: BaseCursor, *, job_ids: Iterable[int] = ()):
    """ Process ready jobs to run on this database.

        The `cron_cr` is used to lock the currently processed job and relased
        by committing after each job.
        """
    for job_id in job_ids:
        try:
            job = IrCron._acquire_one_job(cron_cr, job_id)
        except psycopg2.extensions.TransactionRollbackError:
            cron_cr.rollback()
            _logger.debug("job %s has been processed by another worker, skip", job_id)
            continue
        if not job:
            _logger.debug("job %s is being processed by another worker, skip", job_id)
            continue
        _logger.debug("job %s acquired", job_id)
        # take into account overridings of _process_job() on that database, check_signaling
        registry = api.Environment(cron_cr, api.SUPERUSER_ID, {}).registry
        # run each job in an insolated context from other jobs
        contextvars.copy_context().run(registry[IrCron._name]._process_job, cron_cr, job)
        cron_cr.commit()
        _logger.debug("job %s updated and released", job_id)


def _check_version(cron_cr):
    """ Ensure the code version matches the database version """
    cron_cr.execute("""
            SELECT latest_version
            FROM ir_module_module
             WHERE name='base'
        """, log_exceptions=False)
    (version,) = cron_cr.fetchone()
    if version is None:
        raise BadModuleState()
    if version != BASE_VERSION:
        raise BadVersion()


def _check_modules_state(cr, jobs):
    """ Ensure no module is installing or upgrading """
    cr.execute("""
            SELECT COUNT(*)
            FROM ir_module_module
            WHERE state LIKE %s
        """, ['to %'])
    (changes,) = cr.fetchone()
    if not changes:
        return

    if not jobs:
        raise BadModuleState()

    # use the max(job['nextcall'], job['write_date']) to avoid the cron
    # reset_module_state for an ongoing module installation process
    # right after installing a module with an old 'nextcall' cron in data
    oldest = min(max(job['nextcall'], job['write_date'] or job['nextcall']) for job in jobs)
    if datetime.now() - oldest < MAX_FAIL_TIME:
        raise BadModuleState()

    # the cron execution failed around MAX_FAIL_TIME * 60 times (1 failure
    # per minute for 5h) in which case we assume that the crons are stuck
    # because the db has zombie states and we force a call to
    # reset_module_states.
    from odoo.modules.loading import reset_modules_state  # noqa: PLC0415
    reset_modules_state(cr)
    cr.commit()


def _get_ready_sql_condition(cr: BaseCursor) -> SQL:
    return SQL("""
            active IS TRUE
            AND (nextcall <= %(now)s
                OR id IN (
                    SELECT cron_id
                    FROM ir_cron_trigger
                    WHERE call_at <= %(now)s
                )
            )
        """, now=cr.now())


def _get_all_ready_jobs(cr: BaseCursor) -> list[dict]:
    """ Return a list of all jobs that are ready to be executed """
    cr.execute(SQL("""
            SELECT *
            FROM ir_cron
            WHERE %s
            ORDER BY failure_count, priority, id
        """, IrCron._get_ready_sql_condition(cr)))
    return cr.dictfetchall()


def _acquire_one_job(cr: BaseCursor, job_id: int, *, include_not_ready: bool = False) -> dict | None:
    """
        Acquire for update the job with id ``job_id``.

        The job should not have been processed yet by the current
        worker. Another worker may process the job again, may that job
        become ready again quickly enough (e.g. self-triggering, high
        frequency, or partially done jobs).

        Note: It is possible that this function raises a
              ``psycopg2.errors.SerializationFailure`` in case the job
              has been processed in another worker. In such case it is
              advised to roll back the transaction and to go on with the
              other jobs.
        """

    # The query must make sure that (i) two cron workers cannot
    # process a given job at a same time. The query must also make
    # sure that (ii) a job already processed in another worker
    # should not be processed again by this one (or at least not
    # before the job becomes ready again).
    #
    # (i) is implemented via `FOR NO KEY UPDATE SKIP LOCKED`, each
    # worker just acquire one available job at a time and lock it so
    # the other workers don't select it too.
    # (ii) is implemented via the `WHERE` statement, when a job has
    # been processed and is fully done, its nextcall is updated to a
    # date in the future and the optional triggers are removed. In
    # case a job has only been partially done, the job is left ready
    # to be acquired again by another cron worker.
    #
    # An `UPDATE` lock type is the strongest row lock, it conflicts
    # with ALL other lock types. Among them the `KEY SHARE` row lock
    # which is implicitly acquired by foreign keys to prevent the
    # referenced record from being removed while in use. Because we
    # never delete acquired cron jobs, foreign keys are safe to
    # concurrently reference cron jobs. Hence, the `NO KEY UPDATE`
    # row lock is used, it is a weaker lock that does conflict with
    # everything BUT `KEY SHARE`.
    #
    # Learn more: https://www.postgresql.org/docs/current/explicit-locking.html#LOCKING-ROWS

    where_clause = SQL("id = %s", job_id)
    if not include_not_ready:
        where_clause = SQL("%s AND %s", where_clause, IrCron._get_ready_sql_condition(cr))
    query = SQL("""
            WITH last_cron_progress AS (
                SELECT id as progress_id, cron_id, timed_out_counter, done, remaining
                FROM ir_cron_progress
                WHERE cron_id = %(cron_id)s
                ORDER BY id DESC
                LIMIT 1
            )
            SELECT *
            FROM ir_cron
            LEFT JOIN last_cron_progress lcp ON lcp.cron_id = ir_cron.id
            WHERE %(where)s
            FOR NO KEY UPDATE SKIP LOCKED
        """, cron_id=job_id, where=where_clause)
    try:
        cr.execute(query, log_exceptions=False)
    except psycopg2.extensions.TransactionRollbackError:
        # A serialization error can occur when another cron worker
        # commits the new `nextcall` value of a cron it just ran and
        # that commit occurred just before this query. The error is
        # genuine and the job should be skipped in this cron worker.
        raise
    except Exception as exc:
        _logger.error("bad query: %s\nERROR: %s", query, exc)
        raise

    job = cr.dictfetchone()

    if not job:     # Job is already taken
        return None

    for field_name in ('done', 'remaining', 'timed_out_counter'):
        job[field_name] = job[field_name] or 0
    return job


def _process_job(cls, cron_cr: BaseCursor, job) -> None:
    """
        Execute the cron's server action in a dedicated transaction.

        In case the previous process actually timed out, the cron's
        server action is not executed and the cron is considered
        ``'failed'``.

        The server action can use the progress API via the method
        :meth:`_commit_progress` to report how many records are done
        in each batch.
        Those progress notifications are used to determine the job's
        ``CompletionStatus`` and to determine the next time the cron
        will be executed:

        - ``'fully done'``: the cron is rescheduled later, it'll be
          executed again after its regular time interval or upon a new
          trigger.

        - ``'partially done'``: the cron is rescheduled ASAP, it'll be
          executed again by this or another cron worker once the other
          ready cron jobs have been executed.

        - ``'failed'``: the cron is deactivated if it failed too many
          times over a given time span; otherwise it is rescheduled
          later.
        """
    env = api.Environment(cron_cr, job['user_id'], {})
    ir_cron = env[cls._name]

    ir_cron._clear_schedule(job)
    failed_by_timeout = (
        job['timed_out_counter'] >= CONSECUTIVE_TIMEOUT_FOR_FAILURE
        and not job['done']
    )

    if not failed_by_timeout:
        status = cls._run_job(job)
    else:
        status = CompletionStatus.FAILED
        cron_cr.execute("""
                UPDATE ir_cron_progress
                SET timed_out_counter = 0
                WHERE id = %s
            """, (job['progress_id'],))
        _logger.error("Job %r (%s) timed out", job['cron_name'], job['id'])

    ir_cron._update_failure_count(job, status)

    if status in (CompletionStatus.FULLY_DONE, CompletionStatus.FAILED):
        ir_cron._reschedule_later(job)
    elif status == CompletionStatus.PARTIALLY_DONE:
        ir_cron._reschedule_asap(job)
        if os.getenv('ODOO_NOTIFY_CRON_CHANGES'):
            cron_cr.postcommit.add(ir_cron._notifydb)  # See: `_notifydb`
    else:
        raise RuntimeError(f"unreachable {status=}")


def _run_job(cls, job) -> CompletionStatus:
    """
        Execute the job's server action multiple times until it
        completes. The completion status is returned.

        It is considered completed when either:

        - the server action doesn't use the progress API, or returned
          and notified that all records has been processed: ``'fully done'``;

        - the server action returned and notified that there are
          remaining records to process, but this cron worker ran this
          server action 10 times already: ``'partially done'``;

        - the server action was able to commit and notify some work done,
          but later crashed due to an exception: ``'partially done'``;

        - the server action failed due to an exception and no progress
          was notified: ``'failed'``.
        """
    timed_out_counter = job['timed_out_counter']

    with cls.pool.cursor() as job_cr:
        start_time = time.monotonic()
        env = api.Environment(job_cr, job['user_id'], {
            'lastcall': job['lastcall'],
            'cron_id': job['id'],
            'cron_end_time': start_time + MIN_TIME_PER_JOB,
        })
        cron = env[cls._name].browse(job['id'])

        status = None
        loop_count = 0
        _logger.info('Job %r (%s) starting', job['cron_name'], job['id'])

        # stop after MIN_RUNS_PER_JOB runs and MIN_TIME_PER_JOB seconds, or
        # upon full completion or failure
        while status is None and (
            loop_count < MIN_RUNS_PER_JOB
            or time.monotonic() < env.context['cron_end_time']
        ):
            cron, progress = cron._add_progress(timed_out_counter=timed_out_counter)
            job_cr.commit()

            success = False
            try:
                # signaling check and commit is done inside `_callback`
                cron._callback(job['cron_name'], job['ir_actions_server_id'])
                success = True
            except Exception:  # noqa: BLE001
                _logger.exception('Job %r (%s) server action #%s failed',
                    job['cron_name'], job['id'], job['ir_actions_server_id'])
            finally:
                done, remaining = progress.done, progress.remaining
                match (success, done, remaining):
                    case (False, d, r) if d and r:
                        # The cron action failed but was nonetheless able
                        # to commit some progress.
                        # Hopefully this failure is temporary.
                        pass

                    case (False, _, _):
                        # The cron action failed, and was unable to commit
                        # any progress this time. Consider it failed even
                        # if it progressed in a previous loop iteration.
                        status = CompletionStatus.FAILED

                    case (True, _, 0):
                        # The cron action completed. Either it doesn't use
                        # the progress API, either it reported no remaining
                        # stuff to process.
                        status = CompletionStatus.FULLY_DONE
                        if progress.deactivate:
                            job['active'] = False

                    case (True, 0, _) if loop_count == 0:
                        # The cron action was able to determine there are
                        # remaining records to process, but couldn't
                        # process any of them.
                        # Hopefully this condition is temporary.
                        status = CompletionStatus.PARTIALLY_DONE
                        _logger.warning("Job %r (%s) processed no record",
                            job['cron_name'], job['id'])

                    case (True, 0, _):
                        # The cron action was able to determine there are
                        # remaining records to process, did process some
                        # records in a previous loop iteration, but
                        # processed none this time.
                        status = CompletionStatus.PARTIALLY_DONE

                    case (True, _, _):
                        # The cron action was able to process some but not
                        # all records. Loop.
                        pass

                loop_count += 1
                progress.timed_out_counter = 0
                timed_out_counter = 0
                job_cr.commit()  # ensure we have no leftovers

                _logger.debug('Job %r (%s) processed %s records, %s records remaining',
                    job['cron_name'], job['id'], done, remaining)

        status = status or CompletionStatus.PARTIALLY_DONE
        _logger.info(
            'Job %r (%s) %s (#loop %s; done %s; remaining %s; duration %.2fs)',
            job['cron_name'], job['id'], status,
            loop_count, done, remaining, time.monotonic() - start_time)

    return status
