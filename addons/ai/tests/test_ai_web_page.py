# Part of Odoo. See LICENSE file for full copyright and licensing details.
from unittest.mock import patch

from odoo.tests import tagged
from odoo.tests.common import TransactionCase
from odoo.tools import mute_logger

from odoo.addons.ai.utils.web_fetch import WebFetchError

_FETCH_PAGE_TEXT = "odoo.addons.ai.models.ai_web_scraper_batch.fetch_page_text"
_TEXT = "Odoo is an open-source suite of business applications."


@tagged("post_install", "-at_install")
class TestAIWebPage(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.agent = cls.env["ai.agent"].create({"name": "Agent URL Source Tests"})

    def setUp(self):
        super().setUp()
        # These tests call the cron method directly, outside of an actual cron job context,
        # so _commit_progress() would otherwise try to really commit the (test) transaction.
        commit_progress_patcher = patch("odoo.addons.base.models.ir_cron.IrCron._commit_progress")
        commit_progress_patcher.start()
        self.addCleanup(commit_progress_patcher.stop)

    def _create_url_source(self, name, url, status="processing", is_active=False):
        page = self.env["ai.web.page"].search([("url", "=", url)]) or self.env["ai.web.page"].create({"url": url})
        source = self.env["ai.agent.source"].create({
            "name": name,
            "agent_id": self.agent.id,
            "type": "url",
            "web_page_id": page.id,
        })
        source.write({"status": status, "is_active": is_active})
        return source

    def test_submit_enqueues_one_batch_with_robots_policy(self):
        source = self._create_url_source("Docs", "https://example.com/docs")
        page = source.web_page_id
        page._submit_to_scraper()

        batch = page.batch_id
        self.assertEqual(batch.state, "pending")
        self.assertEqual(batch.callback_model, "ai.web.page")
        self.assertEqual(batch.url_payloads, [{"url": "https://example.com/docs", "check_robots_txt": True}])

    def test_cron_fetches_content_and_syncs_sources(self):
        source = self._create_url_source("Docs", "https://example.com/docs")
        page = source.web_page_id
        page._submit_to_scraper()

        with (
            patch(_FETCH_PAGE_TEXT, return_value=_TEXT) as fetch,
            patch("odoo.addons.ai.models.ai_agent_source.AIAgentSource._trigger_embedding_generation") as trigger,
        ):
            self.env["ai.web.scraper.batch"]._cron_run_web_scraper()

        fetch.assert_called_once_with("https://example.com/docs", check_robots_txt=True)
        self.assertEqual(page.content, _TEXT)
        self.assertFalse(page.batch_id)
        self.assertFalse(self.env["ai.web.scraper.batch"].search([]))
        trigger.assert_called()

    @mute_logger("odoo.addons.ai.models.ai_web_scraper_batch")
    def test_fetch_errors_fail_the_source_with_a_message(self):
        source = self._create_url_source("Private", "https://example.com/private")
        page = source.web_page_id
        page._submit_to_scraper()

        with patch(_FETCH_PAGE_TEXT, side_effect=WebFetchError("robots_disallowed")):
            self.env["ai.web.scraper.batch"]._cron_run_web_scraper()

        self.assertEqual(source.status, "failed")
        self.assertEqual(
            source.error_details,
            "The website's robots.txt does not allow fetching this URL.",
        )
        self.assertFalse(page.batch_id)

    @mute_logger("odoo.addons.ai.models.ai_web_scraper_batch")
    def test_blocked_urls_fail_the_source(self):
        source = self._create_url_source("Internal", "http://127.0.0.1/admin")
        source.web_page_id._submit_to_scraper()

        with patch(_FETCH_PAGE_TEXT, side_effect=WebFetchError("blocked_url")):
            self.env["ai.web.scraper.batch"]._cron_run_web_scraper()

        self.assertEqual(source.status, "failed")
        self.assertEqual(source.error_details, "This URL is not allowed to be fetched.")

    def test_page_without_text_fails_the_source(self):
        source = self._create_url_source("Empty", "https://example.com/empty")
        source.web_page_id._submit_to_scraper()

        with patch(_FETCH_PAGE_TEXT, return_value=""):
            self.env["ai.web.scraper.batch"]._cron_run_web_scraper()

        self.assertEqual(source.status, "failed")
        self.assertEqual(source.error_details, "No text content could be extracted from this URL.")

    def test_reset_for_scraping_detaches_and_resubmits(self):
        source = self._create_url_source("Docs", "https://example.com/reset")
        page = source.web_page_id
        page._submit_to_scraper()
        first_batch = page.batch_id

        page._reset_for_scraping()

        self.assertNotEqual(page.batch_id, first_batch)
        self.assertEqual(page.batch_id.state, "pending")
        self.assertEqual(page.batch_id.url_payloads[0]["url"], "https://example.com/reset")
