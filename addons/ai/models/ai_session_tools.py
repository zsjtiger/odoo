# Part of Odoo. See LICENSE file for full copyright and licensing details.
"""Tool calls of an AI session: running them, pausing for the user, and resuming."""

import copy
import json
import logging
import secrets
from textwrap import dedent

from odoo import Command
from odoo import models
from odoo.exceptions import ConcurrencyError, UserError
from odoo.orm.database.sql_db import PG_CONCURRENCY_EXCEPTIONS_TO_RETRY
from odoo.tools import html_sanitize


from ..utils.ai_utils import format_tool_result, format_tool_summary, UserInputResponse
from ..utils.formatting import markdown_format
from ..utils.types import (
    PendingInteractionResponse,
)

_logger = logging.getLogger(__name__)


DEFAULT_SESSION_SCOPED_TOOLS = [
    "ai.ir_actions_server_ask_user_question",
]

SUBAGENT_TOOL_XMLIDS = (
    'ai.ir_actions_server_start_session',
    'ai.ir_actions_server_continue_session',
)


class AiSessionToolsMixin(models.AbstractModel):
    """Methods of AiSession that run and resume tool calls."""
    _name = 'ai.session.tools.mixin'
    _description = 'AI Session Tools'

    def _get_session_default_tools(self):
        """Return the agent's default tools and tools available only in stateful sessions."""
        self.ensure_one()
        tools = self.agent_id._get_default_tools()
        if not self.env.user.share:
            for xmlid in DEFAULT_SESSION_SCOPED_TOOLS:
                if tool := self.env.ref(xmlid, raise_if_not_found=False):
                    tools |= tool
        if self.agent_id.allowed_agent_ids and self._can_start_subsession():
            for xmlid in SUBAGENT_TOOL_XMLIDS:
                tools |= self.env.ref(xmlid)
        return tools

    def _can_start_subsession(self) -> bool:
        self.ensure_one()
        max_depth = max(1, self.env['ir.config_parameter'].sudo().get_int('ai.max_subsession_depth', 4))
        # Count agent levels, with the root agent at level one.
        ancestor, depth = self, 1
        while ancestor.parent_session_id:
            ancestor, depth = ancestor.parent_session_id, depth + bool(ancestor.agent_id)
        return depth < max_depth

    def _initialize_tool_state(self, state):
        skills = self.env['ai.skill'].sudo().browse(state.get('loaded_skills', []))
        skills &= self.agent_id.sudo()._get_available_skills()
        web_search_skill = self.env.ref('ai.ai_skill_web_search').sudo()
        if self.enable_web_search:
            skills |= web_search_skill
        else:
            skills -= web_search_skill

        state['loaded_skills'] = skills.ids
        state['available_tools'] = (self._get_session_default_tools() | skills.tool_ids).ids

    def _build_tools_context(self, state):
        """Wrap saved tool state with temporary values for this execution."""
        self.ensure_one()
        return {
            'session_id': self.id,
            'state': state,
            'message_body_suffix': self.message_body_suffix,
            'res_model': self.res_model,
            'res_id': self.res_id,
            'agent_id': self.agent_id.id,
            'final_message': False,
            'user_input_request': None,
            'tool_request_confirmed': False,
            'auto_confirm': self._root_session().auto_confirm,
            'user_id': self.env.user.id,
            'enable_web_search': self.enable_web_search,
        }

    def _get_tool_execution_context(self):
        """Return extra context for each tool call, including earlier tool changes."""
        return {}

    def _check_active_session_limit(self) -> None:
        self.ensure_one()
        root = self._root_session()
        active_sessions = self.with_context(active_test=False).search_count([
            ('parent_session_id', 'child_of', root.id),
            ('agent_id', '!=', False),
            ('loop_state', '!=', 'ready'),
        ])
        limit = self.env['ir.config_parameter'].sudo().get_int('ai.max_active_sessions', 20)
        if active_sessions >= limit:
            raise UserError(self.env._("The session tree has reached its active-session limit."))

    def _merge_child_result(self, child, result):
        """Replace a child marker and advance the parent when its loop can continue."""
        pending_batch = self.pending_tool_call or {}
        pending_results = pending_batch.get('pending_results', [])
        child_marker = next((result for result in pending_results if result.get('child_session_id') == child.id), None)
        if not child_marker or child.parent_session_id != self:
            return
        tool_result = format_tool_result(
            {'name': child_marker['tool_name'], 'call_id': child_marker['tool_call_id']},
            result={'session_id': child.id, **result},
        )
        tool_result['success'] = result['status'] == 'completed'
        file_parts = self.env['ir.attachment'].browse(result['attachment_ids'])._ai_read()[1]
        tool_result['result'] += file_parts
        child_marker.clear()
        child_marker.update(tool_result)
        self.pending_tool_call = pending_batch

        if self.loop_state != 'waiting_child' or pending_batch.get('call_id'):
            # Maybe a warning?
            return
        has_pending_children = any('child_session_id' in result for result in pending_results)
        if has_pending_children:
            return None
        if pending_batch.get('declined'):
            self.event_ids = [Command.create({'metadata': self._format_tool_output_message(pending_results)})]
            return self._finish_exchange("declined", content=pending_batch.get('final_message') or self.env._('Skipped'))
        return self._finish_tool_batch(
            pending_results, self._build_tools_context(self.state or {}),
            pending_batch.get('final_message'),
        )

    def _advance_tool_batch(self, pending_tool_response=None) -> None:
        """Consume tool events until the batch finishes or reaches its next wait."""
        self.ensure_one()
        pending = self.pending_tool_call or {}
        tools_context = self._build_tools_context(self.state or {})
        if pending.get('final_message'):
            tools_context['final_message'] = pending['final_message']
        tool_calls = self._get_last_tool_calls()
        if self.request_round >= self.request_round_limit:
            tools = self.env.ref("ai.ir_actions_server_ask_user_question").sudo()
        else:
            tools = self.env['ir.actions.server'].sudo().browse(tools_context['state']['available_tools']).exists()
        items = self._handle_tool_calls(
            tool_calls, {tool.ai_tool_name: tool for tool in tools},
            tools_context, self._get_related_record(), pending_tool_response,
            previous_results=pending.get('pending_results'),
        )
        client_tools = []
        for item in items:
            if 'intermediary_message' in item:
                self.post_agent_step(
                    markdown_format(item['intermediary_message']),
                    'notification' if item.get('is_tool_summary') else 'comment',
                )
            elif 'notifications' in item:
                self.turn_notifications = (self.turn_notifications or []) + item['notifications']
            elif 'client_tool' in item and item['client_tool'].get('oneway'):
                client_tools.append(item['client_tool'])
            elif 'tool_results' in item:
                tool_results = item['tool_results']
                final_message = item.get('final_message')
                if any('child_session_id' in result for result in tool_results):
                    self.write({
                        'loop_state': 'waiting_child', 'resume_token': False,
                        'pending_tool_call': {
                            'pending_results': tool_results, 'final_message': final_message,
                        },
                        'state': tools_context['state'],
                        'message_body_suffix': tools_context['message_body_suffix'],
                    })
                    self._publish_response_state()
                else:
                    self._finish_tool_batch(tool_results, tools_context, final_message)
                break
            else:
                pending = item['pending_tool_call']
                if tools_context['final_message']:
                    pending['final_message'] = tools_context['final_message']
                if 'client_tool' in item:
                    pending['client_tool'] = item['client_tool']
                    # A browser resume may come from a different tab than the last model request.
                    pending['ai_session_identifier'] = self.env.context.get('ai_session_identifier')
                    loop_state = 'waiting_client_result'
                elif 'external_wait_message' in item:
                    pending['await_external_result'] = True
                    loop_state = 'waiting_external_result'
                    self._post_ai_response(item['external_wait_message'])
                else:
                    pending['user_input_request'] = item['user_input_request']
                    loop_state = {
                        'confirmation': 'waiting_confirmation', 'question': 'waiting_answer',
                    }[item['user_input_request']['type']]
                self._set_pending_tool_call(pending)
                self.write({
                    'loop_state': loop_state,
                    'resume_token': secrets.token_urlsafe(32),
                    'state': tools_context['state'],
                    'message_body_suffix': tools_context['message_body_suffix'],
                })
                break

        if client_tools:
            self.channel_id._bus_send('ai.session/client_tools', {
                'channel_id': self.channel_id.id, 'commands': client_tools,
                'aiSessionIdentifier': self.env.context.get('ai_session_identifier'),
            })
        if 'pending_tool_call' in item:
            self._publish_response_state()

    def _finish_tool_batch(self, tool_results, tools_context, final_message=None) -> None:
        self.write({
            'state': tools_context['state'],
            'message_body_suffix': tools_context['message_body_suffix'],
        })
        if self.parent_session_id and final_message:
            tool_results[-1]['result'] += final_message
        self.event_ids = [Command.create({'metadata': self._format_tool_output_message(tool_results)})]
        if final_message is not None:
            return self._finish_exchange(content=self._format_final_message(final_message))
        if self.request_round >= self.request_round_limit:
            return self._finish_exchange('failed', content=self.env._(
                "The AI used too many successive tool rounds. Please try a more precise request."
            ))
        self._submit_agent_request()

    def _resume_pending_interaction(
        self, response: PendingInteractionResponse,
        ai_session_config=None, *, automatic=False,
    ) -> None:
        """Consume one durable interaction and continue its persisted tool batch."""

        self.ensure_one()
        pending_tool_call = self.pending_tool_call
        if self.loop_state == 'waiting_external_result':
            if response['kind'] == 'skip':
                return self._abort_pending_tools()
            if response['kind'] != 'async' or response['call_id'] != pending_tool_call['call_id']:
                return
        elif response['kind'] == 'async':
            return
        if unavailable_message := self._get_session_advance_unavailable_message():
            self._post_ai_response(unavailable_message)
            return

        if self.loop_state in ('waiting_confirmation', 'waiting_answer'):
            user_input_request = pending_tool_call['user_input_request']
            prompt_body = html_sanitize(
                user_input_request['body'], sanitize_attributes=True, sanitize_style=True,
            )
            self._post_ai_response(prompt_body, is_user_input_request=True)

        ai_session_config = ai_session_config or {}
        if response['kind'] == 'confirmation' and response['value'] == UserInputResponse.AUTO_CONFIRM:
            ai_session_config['auto_confirm'] = True
        if ai_session_config:
            self._root_session().update_session_config(ai_session_config)

        if response['kind'] == 'skip':
            return self._abort_pending_tools()

        if self.loop_state == "waiting_confirmation":
            confirmation_value = response["value"]
            selected_choice = next(
                (
                    choice
                    for choice in user_input_request["choices"]
                    if choice["value"] == confirmation_value
                ),
                None,
            )
            if not selected_choice:
                raise UserError(self.env._("This AI confirmation choice is no longer available."))
            if automatic:
                self.turn_notifications = (self.turn_notifications or []) + [{
                    'type': 'ai_note',
                    'body': self.env._("Approved automatically because auto-approval is enabled for this chat."),
                }]
            else:
                self.channel_id.sudo().message_post(
                    body=selected_choice["label"],
                    message_type="comment",
                    subtype_xmlid="mail.mt_comment",
                )
            if confirmation_value == UserInputResponse.DECLINE:
                return self._abort_pending_tools()
        elif self.loop_state == "waiting_answer":
            values = response['value']
            selected_values = set(values)
            selected_choices = [
                choice
                for choice in user_input_request["choices"]
                if choice["value"] in selected_values
            ]
            known_values = {choice["value"] for choice in selected_choices}
            free_text_values = [
                value.strip() for value in values if value not in known_values
            ]
            ordered_values = [
                choice["value"] for choice in selected_choices
            ] + free_text_values
            ordered_labels = [
                choice["label"] for choice in selected_choices
            ] + free_text_values
            if (
                (not user_input_request["multi_select"] and len(values) != 1)
                or (
                    free_text_values
                    and (
                        not user_input_request["allow_free_text"]
                        or len(free_text_values) != 1
                    )
                )
                or len(ordered_values) != len(values)
            ):
                raise UserError(self.env._("This AI question response is not valid."))
            self.channel_id.sudo().message_post(
                body=", ".join(ordered_labels),
                message_type="comment",
                subtype_xmlid="mail.mt_comment",
            )
            response = {'kind': 'question', 'value': ordered_values}
        # Resuming a pending tool starts a fresh allowance, as in the synchronous loop.
        self.request_round_limit = self.request_round + (
            self.env['ir.config_parameter'].sudo().get_int('ai.max_successive_calls') or 30
        )
        return self._advance_tool_batch(response)

    def _deliver_subagent_result(self, content, *, status='completed'):
        """Pass this child's completed answer directly into its parent's pending batch."""
        if content is None:
            if status == 'declined':
                content = self.env._('Declined by the user. Do not attempt to run this sub-agent again unless explicitly instructed.')
            else:
                content = ''
        body, attachment_ids = self._prepare_response_content(content)
        self.env['ai.attachment.vacuum'].mark_attachments_used(attachment_ids)
        self.parent_session_id._merge_child_result(self, {
            'status': status, 'message': str(body), 'attachment_ids': attachment_ids,
            'sources': (self.state or {}).get('web_sources', {}),
        })

    def _format_tool_output_message(self, tool_outputs):
        return {'role': 'user', 'content': [
            {'type': 'tool_result', **result} for result in tool_outputs
        ]}

    def _handle_tool_calls(
        self, tool_calls, tools_by_name, tools_context, record,
        pending_tool_response: PendingInteractionResponse | None = None, previous_results=None,
    ):
        """Processes a list of tool calls and returns the results.

        :param tool_calls: list of tool call dicts
        :param tools_by_name: dict of tool actions by name
        :param tools_context: tools_context to pass in the tools
        :param record: record on which to execute the tools
        :param pending_tool_response: response used to resume the first tool call, if any
        :param previous_results: completed prefix of this provider batch, including child markers
        :return: tool_results
        """
        max_tools_per_call = self.env["ir.config_parameter"].sudo().get_int("ai.max_tool_calls_per_call") or 20
        tool_results = copy.deepcopy(previous_results or [])
        failed_tool_call = any(result.get('success') is False for result in tool_results)
        record_context = {
            'active_model': record._name,
            'active_id': record.id,
            'active_ids': record.ids,
        } if record else {}

        for tc_idx, tool_call in enumerate(tool_calls[len(tool_results):], start=len(tool_results)):
            if tc_idx >= max_tools_per_call:
                # is this needed? tool calls are not the bottleneck, might be better to call
                # them now than having an additional round trip and call them in next iter
                tool_results.append(format_tool_result(tool_call, error="Not executed (tool call limit reached)"))
                if tc_idx == max_tools_per_call:
                    _logger.warning("AI: Tool call limit reached, stopping further tool calls")
                    failed_tool_call = True
                continue
            tools_context['tool_request_confirmed'] = (
                bool(pending_tool_response and pending_tool_response['kind'] == 'confirmation')
                or bool(tools_context['auto_confirm'])
            )
            if pending_tool_response:
                response, pending_tool_response = pending_tool_response, None
                if response['kind'] == 'client_result':
                    tool_results.append(format_tool_result(tool_call, result=response['value']))
                    continue
                if response['kind'] == 'client_error':
                    tool_results.append(format_tool_result(tool_call, error=response['value']))
                    failed_tool_call = True
                    continue
                if response['kind'] == 'question':
                    tool_results.append(format_tool_result(tool_call, result=f"USER ANSWER: {','.join(response['value'])}"))
                    continue
            tools_context['final_message'] = None
            if tool_call['name'] not in tools_by_name:
                _logger.error("AI: Try to call a non-available tool %s", tool_call['name'])
                tool_results.append(format_tool_result(tool_call, error=f"Unknown tool '{tool_call['name']}'"))
                failed_tool_call = True
                continue
            tools_context['user_input_request'] = None
            tools_context['await_external_result'] = False
            tools_context['external_wait_message'] = None
            tools_context['result'] = None
            tool = tools_by_name[tool_call['name']]
            tools_context['tool_call_id'] = tool_call['call_id']
            tool_args = dict(tool_call['args'])
            tool_args.pop('tool_status', None)
            tools_context_before_call = copy.deepcopy(tools_context)
            try:
                tool_result = tool.with_context(**(record_context | self._get_tool_execution_context()))._ai_tool_run(
                    record, tool_args, tools_context,
                )
            except (*PG_CONCURRENCY_EXCEPTIONS_TO_RETRY, ConcurrencyError):
                raise
            except Exception as e:  # noqa: BLE001
                tools_context.clear()
                tools_context.update(tools_context_before_call)
                tool_results.append(format_tool_result(tool_call, error=f"Tool call failed: {e}"))
                exception_msg = f"{tool_call['name']}: failed with the following error: {e}"
                _logger.warning(exception_msg, exc_info=_logger.isEnabledFor(logging.DEBUG))
                yield {
                    'intermediary_message': format_tool_summary({'icon': 'warning', 'text': tool.name}, tool_call),
                    'is_tool_summary': True,
                }
                failed_tool_call = True
                continue
            if isinstance(tool_result, dict):
                yield {
                    'intermediary_message': format_tool_summary(tool_result.get("summary", {'text': tool.name}), tool_call),
                    'is_tool_summary': True,
                }
                if 'child_session_id' in tool_result:
                    tool_results.append({
                        'tool_name': tool_call['name'], 'tool_call_id': tool_call['call_id'],
                        'child_session_id': tool_result['child_session_id'],
                    })
                    continue
                if action := tool_result.get('action'):
                    # tmp backward compatibility
                    # should harmonize the result dict and move stuff from tool context to it
                    yield {'client_tool': {'name': 'do_action', 'params': {'action': action}, 'oneway': True}}
                if client_tool := tool_result.pop('client_tool', None):
                    if not client_tool.get('oneway'):
                        yield {
                            'client_tool': client_tool,
                            'pending_tool_call': {
                                'call_id': tool_call['call_id'],
                                'pending_results': tool_results,
                            }
                        }
                        return
                    yield {'client_tool': client_tool}
                if 'response' in tool_result:
                    tool_result = tool_result['response']
            else:
                yield {
                    'intermediary_message': format_tool_summary({'text': tool.name}, tool_call),
                    'is_tool_summary': True,
                }
            if links := tools_context.pop("preview_links", None):
                yield {'notifications': [{'type': 'ai_preview', 'body': link} for link in links]}
            if user_input_request := tools_context['user_input_request']:
                yield {
                    'user_input_request': user_input_request,
                    'pending_tool_call': {
                        'call_id': tool_call['call_id'],
                        'pending_results': tool_results,
                    },
                }
                return
            if tools_context['await_external_result']:
                yield {
                    'external_wait_message': tools_context['external_wait_message'] or self.env._("Waiting for an external result…"),
                    'pending_tool_call': {
                        'call_id': tool_call['call_id'],
                        'pending_results': tool_results,
                    },
                }
                return
            tool_results.append(format_tool_result(tool_call, result=tool_result))
        item = {'tool_results': tool_results}
        if not failed_tool_call and (final_message := tools_context['final_message']):
            item['final_message'] = final_message
        yield item

    def _abort_pending_tools(self):
        """Decline the remaining tools, wait for launched children, and post the interruption note."""
        self.ensure_one()
        pending_batch = self.pending_tool_call
        pending_results = pending_batch['pending_results']
        last_tool_calls = self._get_last_tool_calls()
        error = "The user chose not to proceed with this. Do not attempt it again unless they bring it up themselves."
        pending_results += [
            format_tool_result(tool_call, error=error)
            for tool_call in last_tool_calls[len(pending_results):]
        ]
        if any('child_session_id' in result for result in pending_results):
            pending_batch['declined'] = True
            pending_batch.pop('call_id', None)
            pending_batch.pop('await_external_result', None)
            self.write({
                'loop_state': 'waiting_child', 'resume_token': False,
                'pending_tool_call': pending_batch,
            })
            self._publish_response_state()
        else:
            self.event_ids = [Command.create({'metadata': self._format_tool_output_message(pending_results)})]
            self._finish_exchange('declined')
        self.turn_notifications = (self.turn_notifications or []) + [{'type': 'ai_note', 'body': self.env._("Skipped")}]
        self._post_turn_notifications()

    def _get_last_tool_calls(self):
        self.ensure_one()
        last_message = self._get_history(1)[0]
        return [part for part in last_message['content'] if part['type'] == 'tool_call']

    def _prepare_tools(self, tools_dict):
        tools_list = []
        for tool_name, tool in tools_dict.items():
            tool_schema = json.loads(dedent(schema).strip()) if (schema := tool.ai_tool_schema) else {'properties': {}, 'required': [], 'type': 'object'}
            if self.env.context.get('ai_show_tool_status'):
                tool_schema['properties']['tool_status'] = {
                    'type': 'string',
                    'description': "The short status displayed while the tool is running. Examples: Searching your leads, Reassigning tasks, Enabling skill (skill_name). It should not contain technical terms.",
                }
                tool_schema['required'].append('tool_status')
            tools_list.append({
                'name': tool_name,
                'instructions': dedent(tool.ai_tool_description).strip() if tool.ai_tool_description else '',
                'schema': tool_schema,
            })
        return tools_list

    def _append_instruction_block(self, base_instructions, tag, parts):
        block = f"\n\n<{tag}>\n" + "\n".join(parts) + f"\n</{tag}>"
        end_marker = "[[END OF INSTRUCTIONS]]"
        if base_instructions.endswith(end_marker):
            return base_instructions[:-len(end_marker)] + block + "\n" + end_marker
        return base_instructions + block

    def _append_loaded_skills(self, base_instructions, state):
        loaded_skill_ids = state.get("loaded_skills")
        if not loaded_skill_ids:
            return base_instructions
        skills = self.env["ai.skill"].sudo().browse(loaded_skill_ids).exists()
        if not skills:
            return base_instructions
        skill_parts = []
        for skill in skills:
            skill_parts.append(
                f'''<skill_content name="{skill.name}" type="{skill.type}">
                {dedent(skill.instructions or "").strip()}
                </skill_content>
                '''
            )
        return self._append_instruction_block(base_instructions, "loaded_skills", skill_parts)

    def _append_subagent_instructions(self, base_instructions):
        if not self.agent_id.allowed_agent_ids:
            return base_instructions
        subagent_parts = [
            (
                "You may start multiple sessions with the same allowed agent. Each session has its own conversation "
                "history and session state; application records remain shared. For independent tasks, issue "
                "ai_tool_start_session calls together in one response, including calls to the same agent. "
                "Wait between calls only when a later task requires an earlier result."
            ),
        ]
        for agent in self.agent_id.allowed_agent_ids:
            subagent_parts.append(f'<agent id="{agent.id}" name="{agent.name}" description="{agent.subtitle}">')
        return self._append_instruction_block(base_instructions, "allowed_subagents", subagent_parts)
