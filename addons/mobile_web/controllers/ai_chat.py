# -*- coding: utf-8 -*-
from odoo import _
from odoo.exceptions import UserError
from odoo.http import Controller, request, route

MAX_PROMPT_LENGTH = 4000
MAX_HISTORY_TURNS = 10
AI_CHAT_INTERFACE_KEY = 'systray_ai_button'


class MobileAIChat(Controller):
    """Question and answer of the mobile AI page, backed by the AI module when it is installed."""

    @route('/mobile_web/ai/ask', type='json', auth='user')
    def mobile_ai_ask(self, prompt, history=None):
        """
        Answer one question with the default agent of the AI chat.

        The mobile page keeps the conversation itself and sends the recent turns with each question,
        so the agent does not need a session. Tools run with the user's rights; a tool that needs a
        confirmation stops the answer, and the user is asked to finish it in the desktop chat.
        """
        if 'ai.composer' not in request.env:
            raise UserError(_("The AI module is not installed."))
        prompt = (prompt or '').strip()
        if not prompt:
            raise UserError(_("Please enter a question."))
        if len(prompt) > MAX_PROMPT_LENGTH:
            raise UserError(_("The question is too long."))
        composer = request.env['ai.composer']._get_composer_from_key_and_model(AI_CHAT_INTERFACE_KEY, None)
        agent = composer.ai_agent_id
        if not agent:
            raise UserError(_("No AI agent is configured for the AI chat."))
        response_parts = agent._generate_single_response([
            {'type': 'text', 'text': _build_message(prompt, history)},
        ])
        if not response_parts:
            return {'text': _("This question needs a confirmation. Continue it in the desktop AI chat.")}
        text = ''.join(part.get('text', '') for part in response_parts if part.get('type') == 'text')
        return {'text': text}


def _build_message(prompt, history):
    """Return the message to the agent: the last turns of the conversation, then the new question."""
    turns = [
        turn for turn in (history or [])[-MAX_HISTORY_TURNS:]
        if isinstance(turn, dict) and turn.get('text')
    ]
    if not turns:
        return prompt
    lines = [
        f"{'User' if turn.get('role') == 'user' else 'Assistant'}: {str(turn['text'])[:MAX_PROMPT_LENGTH]}"
        for turn in turns
    ]
    return "# Conversation so far\n" + "\n".join(lines) + f"\n\n# Current question\n{prompt}"
