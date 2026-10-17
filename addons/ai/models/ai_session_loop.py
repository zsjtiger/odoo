# Part of Odoo. See LICENSE file for full copyright and licensing details.
"""The request loop of an AI session: submitting completions and handling their results."""

import logging
import uuid
from markupsafe import Markup
from textwrap import dedent
from typing import Literal, Unpack

from odoo import Command, fields
from odoo import models
from odoo.exceptions import AccessError, UserError
from odoo.tools import html_sanitize

from odoo.addons.mail.tools.discuss import Store

from ..utils.ai_citation import apply_web_citations
from ..llm import JOB_COMPLETION, LLMError
from ..utils.ai_utils import enable_tools, get_ai_int_param, get_llm_client, get_text_from_parts
from ..utils.formatting import markdown_format
from ..utils.types import (
    AIMessageParts, CompletionFailure, CompletionOptions, CompletionResponse,
    CompletionSuccess, Message, Tool,
)

from .ai_session_tools import SUBAGENT_TOOL_XMLIDS

_logger = logging.getLogger(__name__)


TURN_LIMIT_WARNING = dedent("""
    <turn_limit_warning>
    You are about to exceed the turn limit.
    Primary Directive: Your next and ONLY action is to call the `ai_tool_ask_user_question` tool.
    Tool Arguments: You MUST provide the following arguments:
        `choices`:
             - Two choices meaning "continue" and "stop here", in the language used in this conversation.
        `question`:
            This must be a single string in the conversation's language, construct it by combining these parts:
            1. A reason for pausing (e.g. "...is taking more steps than I can complete in one go, so I've paused here").
            2. A summary of your progress so far (e.g. "I have found the partners in California...").
            3. A description of the next step (e.g. "...and am about to check their open opportunities.").
            4. A direct question asking to proceed (e.g. "Would you like me to continue?").
    </turn_limit_warning>
""").strip()


class AiSessionLoopMixin(models.AbstractModel):
    """Methods of AiSession that submit completion requests and continue the agent loop."""
    _name = 'ai.session.loop.mixin'
    _description = 'AI Session Loop'

    def _publish_response_state(self):
        self.ensure_one()
        if self.channel_id:
            Store(bus_channel=self.channel_id).add(self, "_store_session_fields")

    def _finish_exchange(self, status='completed', *, content=None):
        """Mark the exchange complete, then post or deliver its result.

        :param status: ``completed`` for normal completion, ``declined`` when
            the user declines or skips pending work, or ``failed`` when the
            exchange fails. All statuses return the session to ``ready``.
            Subagents include this status in the result delivered to their parent.
        """
        self.ensure_one()
        self.write({
            'loop_state': 'ready',
            'resume_token': False, 'pending_tool_call': False,
        })
        self._publish_response_state()
        if self.parent_session_id:
            self._post_turn_notifications()
            self._deliver_subagent_result(content, status=status)
        else:
            if content is not None:
                self._post_ai_response(content)
            self._post_turn_notifications()

    def _get_model_round_options(self):
        """Return model options that optional addons may extend per model round."""
        self.ensure_one()
        return {
            'usage': self.agent_id._get_usage_string(),
            'boost_reasoning': self.enable_think_longer,
        }

    def _prepare_response_content(self, content: AIMessageParts | str | Markup):
        """Extract the body and create or reuse inline attachments."""
        self.ensure_one()
        if isinstance(content, str):
            content = [{'type': 'text', 'text': content}]

        inline_data_parts = [part for part in content if part['type'] == 'inline_data']
        attachment_vals = []
        attachment_ids = []
        for ai_response_part in inline_data_parts:
            if attachment_id := ai_response_part.get('metadata', {}).get('attachment_id'):
                attachment_ids.append(attachment_id)
            else:
                title = f'AI Generated image by {self.agent_id.name} ({uuid.uuid4().hex[:8]})'
                attachment_vals.append({
                    'raw': ai_response_part['data'],
                    'mimetype': ai_response_part['mimetype'],
                    'name': title,
                    'description': title,
                })
        if attachment_vals:
            new_attachment_ids = self.env['ai.attachment.vacuum']._create_attachments_and_mark_unused(attachment_vals)
            attachment_ids.extend(new_attachment_ids.ids)
        return get_text_from_parts(content) or '', attachment_ids

    def _post_ai_response(self, content: AIMessageParts | str | Markup, is_user_input_request=False):
        """Post the response in this session's chat."""
        body, attachment_ids = self._prepare_response_content(content)
        if is_user_input_request:
            body = Markup('<div class="ai_user_input_request">%s</div>') % body
        message_data = {
            'author_id': self._root_session().agent_id.partner_id.id,
            'message_type': "comment",
            'silent': True,
            'subtype_xmlid': 'mail.mt_comment',
        }
        if body:
            message_data['body'] = body
        if attachment_ids:
            message_data['attachment_ids'] = attachment_ids
        self.channel_id.message_post(**message_data)

    def _post_turn_notifications(self):
        """Posts the notifications collected during the turn and reset the field:
        notifications, such as previews or config changes, are shown after the turn's response
        """
        self.ensure_one()
        if self.parent_session_id:
            self.turn_notifications = None
            return
        for notification in self.turn_notifications or []:
            body = notification['body']
            if notification['type'] == 'ai_preview':
                body = html_sanitize(body)
            body = Markup("<div class='o_mail_notification' data-oe-type='%s'>%s</div>") % (notification['type'], body)
            self.channel_id.message_post(
                body=body,
                author_id=self.agent_id.partner_id.id,
                subtype_xmlid="mail.mt_comment",
                silent=True,
            )
        self.turn_notifications = None

    def post_agent_step(self, message, message_type):
        """Posts a progress message, which is either a message generated by the agent that explains
        what it is doing, or a tool call summary.
        If the user is not an internal user, the message is logged instead of posted because they
        should not receive these messages, but internal users can use them for debugging
        :param message: The content of the message to post
        :param message_type: 'notification' for the tool summary, 'comment' for the agent message
        """
        self.ensure_one()
        # Child activity stays in its session history; only the main agent posts progress.
        if self.parent_session_id:
            return
        last_event_id = self.event_ids[0].id
        message = Markup('<div class="o-ai-agent-step" data-id="%s">%s</div>') % (last_event_id, message)
        if self.env.user._is_internal():
            return self.channel_id.message_post(
                body=message,
                author_id=self.agent_id.partner_id.id,
                message_type=message_type,
                subtype_xmlid="mail.mt_note",
                is_internal=True,
                silent=True,
            )
        else:
            self.channel_id._message_log(
                body=message,
                author_id=self.agent_id.partner_id.id,
                message_type=message_type
            )

    def _format_final_message(self, response_parts):
        """Apply the existing visible final-message formatting outside the loop stack."""
        self.ensure_one()
        text = get_text_from_parts(response_parts)
        if text and self.enable_web_search and "[WEB_SOURCE:" in text:
            text = apply_web_citations(
                text,
                (self.state or {}).get('web_sources', {}),
                link_attrs='target="_blank" rel="noreferrer noopener"',
            )
        if text and self.agent_id.sources_ids:
            text = self.agent_id._get_llm_response_with_sources(text)
        if text:
            text = markdown_format(text)
        if suffix := self.message_body_suffix:
            text += suffix
            self.message_body_suffix = False
        return [
            *([{'type': 'text', 'text': text}] if text else []),
            *[part for part in response_parts if part['type'] != 'text'],
        ]

    def _get_history(self, limit=None):
        self.ensure_one()
        # reverse them to get the most recent event at the end of the list
        return self.env['ai.session.event'].search([('ai_session_id', '=', self.id)], limit=limit)[::-1].mapped('metadata')

    def _get_request_context_snapshot(self, context=None):
        """Capture bounded context from the environment executing this event."""
        context = self.env.context if context is None else context
        snapshot = {key: context[key] for key in (
            'allowed_company_ids', 'active_company_ids', 'current_view_info',
            'HTTP_HOST', 'lang', 'tz', 'cron_id', 'ai_session_identifier',
            'debug', 'ai_show_tool_status',
        ) if key in context}
        accessible_company_ids = frozenset(self.env.user.company_ids.ids)
        for key in ('allowed_company_ids', 'active_company_ids'):
            if key in snapshot:
                snapshot[key] = [company_id for company_id in snapshot[key] if company_id in accessible_company_ids]
        return snapshot

    def _process_completion_result(
        self, llm_result: CompletionResponse | Literal[False],
    ) -> None:
        """Continue a waiting session with its completion result."""
        self.ensure_one()
        context = self.request_context or {}
        env = self.env(user=self.request_user_id, context=context, su=False)
        self_user = self.with_env(env)
        if self_user.request_guest_id:
            self_user = self_user.with_context(guest=self_user.env['mail.guest'].browse(self_user.request_guest_id.id))
        self_user = self_user.with_context(discuss_channel=self_user.env['discuss.channel'].browse(self_user.channel_id.id))
        self_sudo = self_user.sudo()
        accessible_company_ids = frozenset(env.user.company_ids.ids)
        for key in ('allowed_company_ids', 'active_company_ids'):
            if any(company_id not in accessible_company_ids for company_id in context.get(key, ())):
                raise AccessError(env._(
                    "Your company access changed while this AI response was running."
                ))
        completion_result: CompletionSuccess | CompletionFailure
        if llm_result is False:
            completion_result = {'kind': 'failure', 'code': 'request_failed'}
        else:
            completion_result = {'kind': 'success', 'message': llm_result['result']}
        match self_sudo.state['callback_type']:
            case 'agent_loop':
                self_sudo._continue_agent_loop(completion_result)
            case 'channel_name':
                self_sudo._continue_channel_name(completion_result)

    def _save_and_submit_request(
        self, payload, *, callback_type,
        request_round, request_round_limit,
        state,
    ) -> None:
        """Save request state and schedule submission after the caller commits."""
        self.ensure_one()
        guest = self.env.context.get("guest")
        vals = {
            "loop_state": "waiting_model",
            "request_uuid": str(uuid.uuid4()),
            "request_round": request_round,
            "request_round_limit": request_round_limit,
            "request_payload": payload,
            "request_user_id": self.env.uid,
            "request_guest_id": guest.id if guest else False,
            "request_context": self._get_request_context_snapshot(),
            "resume_token": False,
            "pending_tool_call": False,
        }
        state["callback_type"] = callback_type
        vals["state"] = state
        self.write(vals)
        self._publish_response_state()
        self.env['ai.llm.job'].enqueue(
            uuid=vals['request_uuid'],
            kind=JOB_COMPLETION,
            payload={
                'messages': payload['messages'],
                'instructions': payload.get('instructions'),
                'tools': payload.get('tools'),
                'options': {k: v for k, v in payload.items() if k not in ('messages', 'instructions', 'tools', 'timeout')},
            },
            callback_model='ai.session',
        )

    def _on_llm_job_done(self, request_uuid, llm_result):
        """Called by the job worker with the outcome of a completion job."""
        session = self.search([
            ('request_uuid', '=', request_uuid),
            ('loop_state', '=', 'waiting_model'),
        ], limit=1)
        if session:
            session._process_completion_result(llm_result)

    def _submit_agent_request(self, message=None) -> None:
        """If no message, it's for the succeeding round."""
        self.ensure_one()
        state = self.state or {}
        is_first_round = message is not None
        if not is_first_round:
            round_no = self.request_round + 1
            round_limit = self.request_round_limit
        else:
            self._initialize_tool_state(state)
            self.message_body_suffix = False
            round_no = 1
            round_limit = get_ai_int_param(self.env, 'ai.max_successive_calls', 30) or 30

        completion_options = self._get_model_round_options()
        messages = self._get_history()
        if message:
            user_event = {'role': 'user', 'content': list(message)}
            self.event_ids = [Command.create({'metadata': user_event})]
            messages.append(user_event)

        if messages:
            self._append_round_context(messages, state, is_first_round)
        updated_instructions = self._append_loaded_skills(
            self.agent_id._get_instructions(
                self.ai_composer_id.default_prompt if not self.parent_session_id else None,
                restrict_to_resources_override=self.enable_resources_only,
            ),
            state,
        )
        if round_no >= round_limit:
            tools = self.env.ref("ai.ir_actions_server_ask_user_question").sudo()
            self._get_last_user_message(messages)['content'].append({
                'type': 'text',
                'text': TURN_LIMIT_WARNING,
            })
        else:
            tools = self._get_round_tools(state)
        if tools and completion_options.get('web_grounding'):
            raise UserError(self.env._(
                "The web grounding option is not supported with tools. Use the web search skill instead."
            ))
        tools_by_name = {tool.ai_tool_name: tool for tool in tools}
        payload = {
            'messages': messages,
            'instructions': updated_instructions,
            'tools': self._prepare_tools(tools_by_name),
            **completion_options,
        }
        if 'ai_tool_start_session' in tools_by_name:
            payload['instructions'] = self._append_subagent_instructions(updated_instructions)
        self._save_and_submit_request(
            payload,
            callback_type="agent_loop",
            request_round=round_no,
            request_round_limit=round_limit,
            state=state,
        )

    def _append_round_context(self, messages, state, is_first_round):
        """Append the retrieved sources of the conversation to its last user message.

        The sources are retrieved on the first round and reused by the following rounds.
        """
        if not is_first_round:
            rag_context = state['rag_context']
        else:
            last_user_message = self._get_last_user_message(messages)
            text = get_text_from_parts(last_user_message['content'])
            rag_context = None
            if text and self.agent_id.sources_ids:
                rag_context = self.agent_id._build_rag_context(text)
            state['rag_context'] = rag_context
        last_user_message = self._get_last_user_message(messages)
        last_user_message['content'].append({
            'type': 'text',
            'text': self._get_context_input(rag_context),
        })

    def _get_round_tools(self, state):
        """Return the tools available for this round, without the subagent tools past the depth limit."""
        tools = self.env["ir.actions.server"].sudo().browse(state.get("available_tools")).exists()
        if not self._can_start_subsession():
            for xmlid in SUBAGENT_TOOL_XMLIDS:
                tools -= self.env.ref(xmlid)
            state['available_tools'] = tools.ids
        return tools

    def _root_session(self):
        session = self
        while session.parent_session_id:
            session = session.parent_session_id
        return session

    def _continue_agent_loop(self, completion_result: CompletionFailure | CompletionSuccess) -> None:
        self.ensure_one()
        if completion_result['kind'] == 'failure':
            error_code = completion_result['code']
            _logger.warning(
                "AI completion request %s failed with code %s",
                self.request_uuid,
                error_code,
            )
            self._finish_exchange('failed', content=self.env._("Oops, it looks like our AI is unreachable"))
            return

        output_message = completion_result['message']
        self.event_ids = [Command.create({'metadata': output_message})]
        if any(part['type'] == 'tool_call' for part in output_message['content']):
            if message := get_text_from_parts([part for part in output_message['content'] if part['type'] == 'text']):
                self.post_agent_step(markdown_format(message), 'comment')
            self._advance_tool_batch()
        else:
            response_parts = [
                part for part in output_message['content']
                if part['type'] in ('text', 'inline_data')
            ]
            self._finish_exchange(content=self._format_final_message(response_parts))

    def _continue_channel_name(self, completion_result):
        self.ensure_one()
        title = (
            get_text_from_parts(completion_result['message']['content']).strip().replace("\n", " ")
            if completion_result['kind'] == 'success' else ''
        )
        if title:
            channel = self._root_session().channel_id
            if channel and channel.channel_type == "ai_chat":
                channel.name = title
        else:
            _logger.warning("AI channel name request %s did not return a title", self.request_uuid)
        self.unlink()

    def _get_context_input(self, rag_context):
        self.ensure_one()
        context = "<odoo_current_context>\n"
        if rag_context:
            context += f"## RAG\n{rag_context}\n"
        context += f"## Date\n{fields.Datetime.now()} (UTC)"
        if self.env.user._is_internal():
            user_info = {k: v for k, v in self.env.user._ai_read(['name', 'function', 'partner_id'])[0][0].items() if v}
            user_info['user_id'] = user_info.pop('id')
        else:
            user_info = {k: v for k, v in self.env.user.partner_id._ai_read(['name', 'function'])[0][0].items() if v}
            user_info['is_public'] = True
        context += f"\n## User info\n{user_info}"

        active_companies = self.env["res.company"].search([("id", "in", self.env.context.get("active_company_ids"))])
        active_companies_infos = []
        for company in active_companies:
            company_info = {
                "model": "res.company",
                "id": company.id,
                "name": company.name,
            }
            if company.country_id.code:
                company_info["country_code"] = company.country_id.code
                if company.city:
                    company_info["country_city"] = company.city
            active_companies_infos.append(company_info)
        context += f"\n## Current active companies\n{active_companies_infos}"
        if view_info := self.env.context.get("current_view_info"):
            context += f"\n## Current view\n{view_info}"
        if related_record := self._get_related_record():
            # add up-to-date record info
            context += f"\n## Current record data\n{related_record._ai_serialize_fields_data()}"
        context += f"\n## Current agent (you)\nName: {self.agent_id.name}\nId: {self.agent_id.id}"
        if self._root_session().auto_confirm:
            context += "\n## Auto confirm\nTool auto-confirmation is enabled"
        context += "</odoo_current_context>"
        return context

    def _get_direct_response(
        self, instructions: str, message: AIMessageParts, tools=None,
        record=None, agent_id=None, on_item_callback=None, **completion_options: Unpack[CompletionOptions]
    ) -> AIMessageParts:
        """Gets a response from the LLM without managing conversation history/session state.

        This method is designed for "one-shot" requests where you need an immediate
        response from the LLM based on a given set of inputs, without needing to
        persist or resume a conversation (eg. server actions).

        :param instructions: System-level instructions or context to guide the LLM's behavior.
        :param message: user message to send to the LLM.
        :param tools: A recordset of `ir.actions.server` representing tools the LLM can call.
        :param record: The current Odoo record related to the request, if any.
        :param agent_id: The agent ID, if any.
        :param on_item_callback: A function to call for each item produced by the agentic loop
        :return: formatted response from the LLM, typically a list of message parts
        """
        tools_context = {
            'state': {},
            'tool_request_confirmed': False,
            'user_input_request': None,
            'await_external_result': False,
            'external_wait_message': None,
            'auto_confirm': False,
            'final_message': False,
            'user_id': self.env.user.id,
            'agent_id': agent_id,
            'enable_web_search': True,  # Allow get_single_response to use web search when the web-search skill is included in the agents accessible skills.
        }

        enable_tools(tools_context, tools.ids if tools else [])
        response_generator = self.env['ai.session']._run_agentic_loop(
            instructions=instructions,
            message=message,
            tools_context=tools_context,
            record=record,
            **completion_options
        )
        for item in response_generator:
            if on_item_callback is not None:
                on_item_callback(item, tools_context)
            if response := item.get('final_message'):
                if completion_options.get('resolve_web_sources', True):
                    for part in response:
                        sources = tools_context['state'].get('web_sources', {}) or part.get('sources', {})
                        if part['type'] != 'text' or not sources or not "[WEB_SOURCE:" in part['text']:
                            continue
                        part['text'] = apply_web_citations(part['text'], sources)
                return response
        return None

    def _run_agentic_loop(self, instructions, message, tools_context, record=None, **completion_options):
        """Internal: runs the LLM completion loop, handling tool calls until done.

        Not meant to be called directly. Use `_get_direct_response` for one-shot
        requests. Stateful conversations use bounded session advances from persisted state.
        """
        max_successive_calls = get_ai_int_param(self.env, "ai.max_successive_calls", 30) or 30
        messages = []
        if message:
            messages.append({'role': 'user', 'content': message})

        for api_request_idx in range(max_successive_calls):
            updated_instructions = self._append_loaded_skills(instructions, tools_context['state'])
            tools = self.env["ir.actions.server"].sudo().browse(tools_context["state"]["available_tools"]).exists()
            # gemini does not support tools + web_grounding so should use a web search tool instead
            # make it so for every provider for consistency (skill prompt etc.)
            if tools and completion_options.get('web_grounding'):
                raise UserError(self.env._("The web grounding option is not supported with tools. Use the web search skill instead."))
            tools_by_name = {tool.ai_tool_name: tool for tool in tools} if tools else {}
            formatted_tools = self._prepare_tools(tools_by_name) if tools else {}
            try:
                response = self._get_completions(
                    messages[:],
                    updated_instructions,
                    formatted_tools,
                    **completion_options,
                )
            except LLMError as e:
                raise UserError(str(e)) from e

            output_message = response['result']
            messages.append(output_message)

            tool_calls = [part for part in output_message['content'] if part['type'] == 'tool_call']
            if tool_calls:
                if message := get_text_from_parts([part for part in output_message['content'] if part['type'] == 'text']):
                    yield {'intermediary_message': message}
                yield {'tool_calls': tool_calls}
                all_tool_results = []
                items_to_yield = []
                for item in self._handle_tool_calls(tool_calls, tools_by_name, tools_context, record):
                    if tool_results := item.get('tool_results'):
                        all_tool_results.extend(tool_results)
                    if item.get('intermediary_message'):
                        yield item
                    else:
                        items_to_yield.append(item)
                if all_tool_results:
                    messages.append(self._format_tool_output_message(all_tool_results))
                for item in items_to_yield:
                    yield item

            else:
                message_parts = [part for part in output_message['content'] if part['type'] in ('text', 'inline_data')]
                yield {'final_message': message_parts}
                return
        raise UserError(self.env._("Number of successive API calls exceeded, please try again with a more precise request."))

    def _get_completions(
        self,
        messages: list[Message],
        instructions: str,
        tools: list[Tool] | None = None,
        **options: Unpack[CompletionOptions],
    ) -> CompletionResponse:
        try:
            message = get_llm_client(self.env).chat_completion(
                messages, instructions=instructions, tools=tools,
                options=dict(options),
            )
        except LLMError as e:
            raise UserError(str(e)) from e
        return {'result': message}

    def _get_last_user_message(self, messages: list[Message]):
        for msg in messages[::-1]:
            if msg['role'] == 'user' and any(part['type'] == 'text' for part in msg['content']):
                return msg
        raise ValueError("No valid user message found in list of messages")
