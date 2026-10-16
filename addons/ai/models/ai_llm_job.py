# Part of Odoo. See LICENSE file for full copyright and licensing details.
import logging
from datetime import timedelta

from odoo import api, fields, models

from ..llm import JOB_COMPLETION, JOB_EMBEDDINGS, JOB_TRANSCRIPTION, job_outcome
from ..utils.ai_utils import get_llm_client

_logger = logging.getLogger(__name__)

BATCH_SIZE = 20
RETENTION = timedelta(days=1)


class AiLlmJob(models.Model):
    """A request to the language model, run asynchronously by a cron worker.

    The result is handed back to the model named in ``callback_model`` through
    ``_on_llm_job_done(uuid, llm_result)``, with the shape described by ``job_outcome``.
    """
    _name = 'ai.llm.job'
    _description = 'AI Language Model Job'
    _order = 'id'

    uuid = fields.Char(required=True, copy=False, index=True)
    kind = fields.Selection(
        [(JOB_COMPLETION, "Completion"), (JOB_EMBEDDINGS, "Embeddings"), (JOB_TRANSCRIPTION, "Transcription")],
        required=True,
    )
    payload = fields.Json(required=True)
    callback_model = fields.Char(required=True)
    state = fields.Selection([('pending', "Pending"), ('done', "Done")], required=True, default='pending', index=True)
    error = fields.Char()
    create_date = fields.Datetime(index=True)

    _uuid_unique = models.Constraint('UNIQUE(uuid)', 'The job UUID must be unique.')

    @api.model
    def enqueue(self, *, uuid, kind, payload, callback_model):
        job = self.sudo().create({
            'uuid': uuid,
            'kind': kind,
            'payload': payload,
            'callback_model': callback_model,
        })
        self.env.ref('ai.ir_cron_run_llm_jobs')._trigger()
        return job

    def _claim_pending(self, limit):
        """Lock and return up to ``limit`` pending jobs; jobs locked by another worker are skipped."""
        self.env.cr.execute(
            "SELECT id FROM ai_llm_job WHERE state = 'pending' ORDER BY id LIMIT %s FOR UPDATE SKIP LOCKED",
            [limit],
        )
        return self.browse([row[0] for row in self.env.cr.fetchall()])

    @api.model
    def _cron_run_pending(self, limit=BATCH_SIZE):
        client_error = None
        try:
            client = get_llm_client(self.env)
        except Exception as e:  # noqa: BLE001 -- reported per job below
            client_error = str(e)
            client = None
        for job in self._claim_pending(limit):
            if client is None:
                llm_result, llm_error = False, client_error
            else:
                llm_result, llm_error = job_outcome(client, job.kind, job.payload)
            job.write({'state': 'done', 'error': llm_error})
            try:
                self.env[job.callback_model].sudo()._on_llm_job_done(job.uuid, llm_result)
            except Exception:  # noqa: BLE001 -- one job must not stop the others
                _logger.exception("Failed to deliver the result of AI job %s", job.uuid)
        self._cron_cleanup()

    @api.model
    def _cron_cleanup(self):
        self.search([
            ('state', '=', 'done'),
            ('create_date', '<', fields.Datetime.now() - RETENTION),
        ]).unlink()
