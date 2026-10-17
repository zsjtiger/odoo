# -*- coding: utf-8 -*-
import json
from unittest.mock import patch

from odoo.tests import HttpCase, TransactionCase, tagged

from odoo.addons.mobile_web.controllers.ai_chat import MAX_HISTORY_TURNS, _build_message


class TestMobileAIChatMessage(TransactionCase):
    """ 手机端 AI 页面: 发给 agent 的消息内容 """

    def test_question_without_history_is_sent_as_is(self):
        self.assertEqual(_build_message('How many customers?', []), 'How many customers?')

    def test_history_is_added_before_the_question(self):
        message = _build_message('And in Texas?', [
            {'role': 'user', 'text': 'Customers in New Jersey?'},
            {'role': 'assistant', 'text': 'Three.'},
        ])
        self.assertIn('User: Customers in New Jersey?', message)
        self.assertIn('Assistant: Three.', message)
        self.assertTrue(message.endswith('# Current question\nAnd in Texas?'))

    def test_only_the_last_turns_are_sent(self):
        history = [{'role': 'user', 'text': f'question {i}'} for i in range(MAX_HISTORY_TURNS + 5)]
        message = _build_message('new', history)
        self.assertNotIn('question 0', message)
        self.assertIn(f'question {MAX_HISTORY_TURNS + 4}', message)

    def test_invalid_turns_are_ignored(self):
        message = _build_message('hello', ['not a dict', {'role': 'user', 'text': ''}, None])
        self.assertEqual(message, 'hello')


@tagged('post_install', '-at_install')
class TestMobileAIChatRoute(HttpCase):
    """ /mobile_web/ai/ask: skipped when the AI module is not installed """

    def setUp(self):
        super().setUp()
        if 'ai.composer' not in self.env:
            self.skipTest('The AI module is not installed')
        self.composer = self.env['ai.composer']._get_composer_from_key_and_model('systray_ai_button', None)
        if not self.composer.ai_agent_id:
            self.skipTest('No default AI agent for the AI chat')
        self.authenticate('admin', 'admin')

    def _ask(self, prompt, history=None):
        response = self.url_open('/mobile_web/ai/ask', data=json.dumps({
            'jsonrpc': '2.0', 'method': 'call',
            'params': {'prompt': prompt, 'history': history or []},
        }), headers={'Content-Type': 'application/json'})
        self.assertEqual(response.status_code, 200)
        return response.json()

    def test_answer_is_the_text_of_the_agent_response(self):
        agent_type = type(self.composer.ai_agent_id)
        with patch.object(agent_type, '_generate_single_response',
                          return_value=[{'type': 'text', 'text': 'Three customers.'}]) as generate:
            body = self._ask('Customers in New Jersey?')
        self.assertEqual(body['result'], {'text': 'Three customers.'})
        self.assertEqual(generate.call_count, 1)

    def test_empty_question_is_rejected(self):
        body = self._ask('   ')
        self.assertIn('error', body)

    def test_pending_confirmation_gives_a_message(self):
        agent_type = type(self.composer.ai_agent_id)
        with patch.object(agent_type, '_generate_single_response', return_value=None):
            body = self._ask('Delete everything')
        self.assertIn('confirmation', body['result']['text'])
