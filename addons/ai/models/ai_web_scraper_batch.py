# Part of Odoo. See LICENSE file for full copyright and licensing details.

import json
import logging

from odoo import api, fields, models

from odoo.addons.ai.utils.web_fetch import WebFetchError, fetch_page_text

_logger = logging.getLogger(__name__)


class AIWebScraperBatch(models.Model):
    _name = 'ai.web.scraper.batch'
    _description = 'AI Web Scraper Batch'

    state = fields.Selection(
        selection=[
            ('pending', 'Pending'),
            ('done', 'Done'),
            ('failed', 'Failed'),
        ],
        default='pending',
        required=True,
        index=True,
    )
    url_payloads = fields.Json(string="URL Payloads")
    result = fields.Json(string="Scraper Result")
    error = fields.Text(string="Error")

    # Model whose `_web_scraper_result_ready` hook is called once the batch
    # reaches a terminal state (see `_cron_run_web_scraper`).
    callback_model = fields.Char(string="Callback Model", required=True)

    _BATCH_SIZE = 20
    _CRON_MAX_BATCHES = 5

    @api.model
    def _enqueue(self, url_payloads, callback_model):
        """Create a scraper batch and schedule it for processing.

        :param url_payloads: list of URL payloads, e.g.
            ``[{'url': ..., 'check_robots_txt': ...}]``
        :type url_payloads: list of dict
        :param callback_model: model implementing ``_web_scraper_result_ready(batch)``,
            called once the batch reaches a terminal state.
        :type callback_model: str
        :return: the created batch
        :rtype: ai.web.scraper.batch
        """
        payloads = []
        for payload in url_payloads:
            if not isinstance(payload, dict) or not payload.get('url'):
                msg = "Scraper url payload must be a dictionary with a url."
                raise TypeError(msg)
            payloads.append({
                'url': payload['url'],
                'check_robots_txt': bool(payload.get('check_robots_txt', True)),
            })
        batch = self.create({
            'url_payloads': payloads,
            'callback_model': callback_model,
        })
        self.env.ref('ai.ir_cron_run_web_scraper')._trigger()
        return batch

    @api.model
    def _cron_run_web_scraper(self):
        cron = self.env['ir.cron']

        # Process pending batches; each batch fetches its URLs synchronously, so
        # the number processed per run is capped and the cron re-triggered.
        pending = self.search([('state', '=', 'pending')], limit=self._CRON_MAX_BATCHES, order='id ASC')
        cron._commit_progress(remaining=len(pending))
        for batch in pending:
            batch._process()
            if not cron._commit_progress(1):
                self.env.ref('ai.ir_cron_run_web_scraper')._trigger()
                return
        if len(pending) >= self._CRON_MAX_BATCHES:
            self.env.ref('ai.ir_cron_run_web_scraper')._trigger()

        # Commit batch results before dispatch, then isolate each consumer in its
        # own transaction. Failed callbacks keep their batch for a later retry.
        batches = self.search([('state', 'in', ('done', 'failed'))])
        if not cron._commit_progress(remaining=len(batches)):
            return
        for batch in batches:
            batch_id, callback_model = batch.id, batch.callback_model
            try:
                self.env[callback_model]._web_scraper_result_ready(batch)
                batch.unlink()
                if not cron._commit_progress(1):
                    return
            except Exception:  # noqa: BLE001
                self.env.cr.rollback()
                _logger.exception(
                    "AI web scraper: %s._web_scraper_result_ready failed for batch %s",
                    callback_model, batch_id,
                )
                if not cron._commit_progress():
                    return

    def _process(self):
        """Fetch every URL of this batch and store the outcome in :attr:`result`."""
        self.ensure_one()
        pages = {}
        for payload in self.url_payloads:
            url = payload['url']
            try:
                text = fetch_page_text(url, check_robots_txt=payload['check_robots_txt'])
            except WebFetchError as e:
                _logger.info("AI web scraper: %s not fetched (%s)", url, e.reason)
                pages[url] = {'failed': True, 'reason': e.reason}
                continue
            except Exception:  # noqa: BLE001
                _logger.exception("AI web scraper: unexpected error while fetching %s", url)
                pages[url] = {'failed': True, 'reason': 'fetch_failed'}
                continue
            pages[url] = {'payload': json.dumps({'text': text})}
        self.write({'state': 'done', 'result': {'pages': pages}})
