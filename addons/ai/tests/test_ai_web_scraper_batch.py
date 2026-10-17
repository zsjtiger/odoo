# Part of Odoo. See LICENSE file for full copyright and licensing details.

from unittest.mock import patch

from odoo.tests import TransactionCase, tagged
from odoo.tools import mute_logger

from odoo.addons.ai.utils.web_fetch import WebFetchError


@tagged('post_install', '-at_install')
class TestAIWebScraperBatch(TransactionCase):

    @mute_logger('odoo.addons.ai.models.ai_web_scraper_batch')
    def test_dispatch_rolls_back_failed_callback_and_keeps_other_commits(self):
        with self.registry_test_mode(), self.registry.cursor() as cr:
            env = self.env(cr=cr)
            partners = env['res.partner'].create([
                {'name': name} for name in ('Before', 'Failure', 'After')
            ])
            batches = env['ai.web.scraper.batch'].create([
                {'state': 'done', 'callback_model': 'ai.web.page', 'url_payloads': [{'url': str(partner.id)}]}
                for partner in partners
            ])
            visited = []

            def callback(pages, batch):
                visited.append(batch.id)
                partner = pages.env['res.partner'].browse(int(batch.url_payloads[0]['url']))
                partner.name = 'Processed'
                partner.flush_recordset(['name'])
                if batch == batches[1]:
                    pages.env.cr.execute('SELECT 1 / 0', log_exceptions=False)

            with patch.object(self.registry['ai.web.page'], '_web_scraper_result_ready', callback):
                env['ai.web.scraper.batch']._cron_run_web_scraper()

            self.assertEqual(visited, batches.ids)
            self.assertEqual(batches.exists(), batches[1])
            self.assertEqual(partners.mapped('name'), ['Processed', 'Failure', 'Processed'])

            # A later rollback must not undo either successful callback.
            cr.rollback()
            self.assertEqual(batches.exists(), batches[1])
            self.assertEqual(partners.mapped('name'), ['Processed', 'Failure', 'Processed'])

    @mute_logger('odoo.addons.ai.models.ai_web_scraper_batch')
    def test_dispatch_rolls_back_when_flush_fails(self):
        with self.registry_test_mode(), self.registry.cursor() as cr:
            env = self.env(cr=cr)
            batch = env['ai.web.scraper.batch'].create({
                'state': 'done', 'callback_model': 'ai.web.page',
            })
            partner = env['res.partner'].create({'name': 'Before'})

            def fail():
                message = 'Flush failed'
                raise ValueError(message)

            def callback(pages, batch):
                partner.name = 'Processed'
                pages.env.cr.precommit.add(fail)

            with patch.object(self.registry['ai.web.page'], '_web_scraper_result_ready', callback):
                env['ai.web.scraper.batch']._cron_run_web_scraper()

            self.assertTrue(batch.exists(), 'The deletion must roll back together with callback writes')
            self.assertEqual(partner.name, 'Before')

    def test_dispatch_stops_when_cron_time_is_exhausted(self):
        with self.registry_test_mode(), self.registry.cursor() as cr:
            env = self.env(cr=cr)
            batches = env['ai.web.scraper.batch'].create([
                {'state': 'done', 'callback_model': 'ai.web.page'} for _ in range(2)
            ])
            commit_progress = self.registry['ir.cron']._commit_progress

            def stop_after_batch(cron, processed=0, **kwargs):
                remaining_time = commit_progress(cron, processed, **kwargs)
                return 0 if processed else remaining_time

            with patch.object(self.registry['ir.cron'], '_commit_progress', stop_after_batch):
                env['ai.web.scraper.batch']._cron_run_web_scraper()

            self.assertEqual(batches.exists(), batches[1])
            cr.rollback()
            self.assertEqual(batches.exists(), batches[1])

    @mute_logger('odoo.addons.ai.models.ai_web_scraper_batch')
    def test_dispatch_stops_after_failure_when_cron_time_is_exhausted(self):
        with self.registry_test_mode(), self.registry.cursor() as cr:
            env = self.env(cr=cr)
            batches = env['ai.web.scraper.batch'].create([
                {'state': 'done', 'callback_model': 'ai.web.page'} for _ in range(2)
            ])
            commit_progress = self.registry['ir.cron']._commit_progress

            def stop_after_failure(cron, processed=0, **kwargs):
                remaining_time = commit_progress(cron, processed, **kwargs)
                return 0 if callback.called else remaining_time

            with (
                patch.object(self.registry['ai.web.page'], '_web_scraper_result_ready', side_effect=ValueError('Failed')) as callback,
                patch.object(self.registry['ir.cron'], '_commit_progress', stop_after_failure),
            ):
                env['ai.web.scraper.batch']._cron_run_web_scraper()

            callback.assert_called_once()
            self.assertEqual(batches.exists(), batches)

    @mute_logger('odoo.addons.ai.models.ai_web_scraper_batch')
    def test_process_records_text_and_failure_per_url(self):
        batch = self.env['ai.web.scraper.batch'].create({
            'callback_model': 'ai.web.page',
            'url_payloads': [
                {'url': 'https://example.com/ok', 'check_robots_txt': True},
                {'url': 'https://example.com/blocked', 'check_robots_txt': False},
            ],
        })

        def fetch(url, check_robots_txt):
            if url.endswith('blocked'):
                message = 'blocked_url'
                raise WebFetchError(message)
            self.assertTrue(check_robots_txt)
            return 'Some text'

        with patch('odoo.addons.ai.models.ai_web_scraper_batch.fetch_page_text', side_effect=fetch):
            batch._process()

        self.assertEqual(batch.state, 'done')
        self.assertEqual(batch.result['pages']['https://example.com/ok']['payload'], '{"text": "Some text"}')
        self.assertEqual(batch.result['pages']['https://example.com/blocked'], {'failed': True, 'reason': 'blocked_url'})

    @mute_logger('odoo.addons.ai.models.ai_web_scraper_batch')
    def test_process_turns_unexpected_errors_into_fetch_failures(self):
        batch = self.env['ai.web.scraper.batch'].create({
            'callback_model': 'ai.web.page',
            'url_payloads': [{'url': 'https://example.com/crash', 'check_robots_txt': True}],
        })
        with patch('odoo.addons.ai.models.ai_web_scraper_batch.fetch_page_text', side_effect=RuntimeError('boom')):
            batch._process()
        self.assertEqual(batch.result['pages']['https://example.com/crash'], {'failed': True, 'reason': 'fetch_failed'})
