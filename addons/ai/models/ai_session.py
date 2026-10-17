# Part of Odoo. See LICENSE file for full copyright and licensing details.

import logging

from odoo import api, fields, models
from odoo.exceptions import AccessError, MissingError, ValidationError
from odoo.tools import html_sanitize

from odoo.addons.ai.utils.ai_utils import disable_skills
from odoo.addons.mail.tools.discuss import Store

_logger = logging.getLogger(__name__)


class AiSessionEvent(models.Model):
    """Holds metadata of a message exchanged with a LLM.
    Metadata can be a list of text messages, tool call requests/results, thinking signatures etc.
    """
    _name = 'ai.session.event'
    _description = 'AI Session Event'
    _order = 'id desc'

    ai_session_id = fields.Many2one('ai.session', ondelete='cascade', index='btree_not_null')
    metadata = fields.Json('json representation of the event', required=True)

    def get_tool_params(self, call_id):
        self.ensure_one()
        if not self.env.user._is_internal():
            raise AccessError(self.env._("Only internal users can view tool parameters."))
        # sudo: access is based on session's channel access (internal users can't access events)
        event_sudo = self.sudo()
        event_sudo.ai_session_id.channel_id.sudo(False).check_access('read')
        tool_call = next(
            (part for part in event_sudo.metadata['content'] if part['type'] == 'tool_call' and part['call_id'] == call_id),
            None,
        )
        if not tool_call:
            return None
        # remove technical args
        return {k: v for k, v in tool_call['args'].items() if k not in {'tool_status', '__final_message', 'explanation'}}


class AiSession(models.Model):
    _name = 'ai.session'
    _inherit = ['ai.session.tools.mixin', 'ai.session.loop.mixin']
    _description = "AI Session"

    active = fields.Boolean(default=True)
    agent_id = fields.Many2one('ai.agent', ondelete='cascade', index='btree_not_null')
    ai_composer_id = fields.Many2one('ai.composer')
    channel_id = fields.Many2one('discuss.channel', ondelete='cascade', index='btree_not_null')
    parent_session_id = fields.Many2one('ai.session', ondelete='cascade', index='btree_not_null')
    event_ids = fields.One2many('ai.session.event', 'ai_session_id')
    state = fields.Json(string="State", help="Field that can be used to store data between tool calls")
    message_body_suffix = fields.Html(copy=False)
    res_model = fields.Char("Model")
    res_id = fields.Many2oneReference(model_field='res_model')
    pending_tool_call = fields.Json("Tool call waiting on the client")
    auto_confirm = fields.Boolean("Automatically confirm tool calls for the session", default=False)
    enable_web_search = fields.Boolean("Enable web search capability for the session")
    enable_think_longer = fields.Boolean("Enable think longer option for the session", default=False)
    enable_resources_only = fields.Boolean("Enable resource restriction for the session")
    show_agent_steps = fields.Boolean("Show agent steps")
    turn_notifications = fields.Json("Notifications collected during a turn, that will be shown after the final response")
    loop_state = fields.Selection([
        ("ready", "Ready"),
        ("waiting_model", "Waiting for Model"),
        ("waiting_confirmation", "Waiting for Confirmation"),
        ("waiting_answer", "Waiting for Answer"),
        ("waiting_client_result", "Waiting for Client Result"),
        ("waiting_external_result", "Waiting for External Result"),
        ("waiting_child", "Waiting for Child Session"),
    ], required=True, default="ready", index=True)
    request_uuid = fields.Char()
    request_payload = fields.Json()
    request_round = fields.Integer()
    request_round_limit = fields.Integer()
    request_user_id = fields.Many2one("res.users", ondelete="restrict")
    request_guest_id = fields.Many2one("mail.guest", ondelete="set null")
    request_context = fields.Json()
    resume_token = fields.Char()

    _request_uuid_unique = models.UniqueIndex(
        "(request_uuid)", "The active request UUID must be unique.",
    )
    _valid_request_round = models.Constraint(
        "CHECK(loop_state = 'ready' OR (request_round IS NOT NULL AND request_round_limit IS NOT NULL "
        "AND request_round >= 1 AND request_round_limit >= request_round))",
        "The active AI request round must be within its exchange limit.",
    )
    _complete_request_data = models.Constraint(
        "CHECK(loop_state = 'ready' OR (request_uuid IS NOT NULL AND request_payload IS NOT NULL "
        "AND request_user_id IS NOT NULL))",
        "An active AI exchange must retain its complete model request data.",
    )
    _complete_interaction_wait = models.Constraint(
        "CHECK(loop_state NOT IN ('waiting_confirmation', 'waiting_answer', "
        "'waiting_client_result', 'waiting_external_result') "
        "OR (resume_token IS NOT NULL AND pending_tool_call IS NOT NULL))",
        "A waiting AI interaction must retain its continuation data.",
    )
    _complete_child_wait = models.Constraint(
        "CHECK(loop_state != 'waiting_child' OR pending_tool_call IS NOT NULL)",
        "A session waiting for a child must retain its pending tool call.",
    )

    def _store_session_fields(self, res: Store.FieldList):
        res.one("channel_id", [])
        res.one("parent_session_id", [])
        res.one("agent_id", ["name", "partner_id"])
        res.attr("res_model")
        res.attr("res_id")
        res.one("ai_composer_id", "_store_composer_fields")
        res.attr("config", lambda session: session.get_session_config())
        res.attr("config_rules", lambda session: session._get_session_config_rules())

        def get_user_input_request(session):
            if session.loop_state not in ("waiting_confirmation", "waiting_answer"):
                return False
            user_input_request = session.pending_tool_call["user_input_request"]
            return {
                "type": user_input_request["type"],
                "body": ['markup', str(html_sanitize(user_input_request['body'], sanitize_attributes=True, sanitize_style=True))],
                "choices": user_input_request["choices"],
                "multiSelect": user_input_request.get("multi_select", False),
                "allowFreeText": user_input_request.get("allow_free_text", False),
                "resumeToken": session.resume_token,
            }

        res.attr("userInputRequest", value=get_user_input_request)
        res.attr(
            "external_pending_tool",
            value=lambda session: bool((session.pending_tool_call or {}).get("await_external_result")),
        )

        def get_current_tool_status(session):
            if session.parent_session_id or not session.env.user._is_internal() or session.loop_state == 'ready':
                return False
            last_turns = session._get_history(2)
            if len(last_turns) != 2:
                # no assistant response yet, so no tool
                return False
            last_assistant_turn = last_turns[0] if last_turns[0]['role'] == 'assistant' else last_turns[1]
            last_tool_calls = [p for p in last_assistant_turn['content'] if p['type'] == 'tool_call']
            if not last_tool_calls:
                return False
            if session.pending_tool_call:
                pending_results = session.pending_tool_call.get('pending_results') or []
                current_tool = last_tool_calls[max(len(pending_results) - 1, 0)]
            else:
                current_tool = last_tool_calls[-1]
            return current_tool['args'].get('tool_status')
        res.attr("toolStatus", value=get_current_tool_status)

        def get_pending_client_tool_request(session):
            if session.loop_state != "waiting_client_result":
                return False
            client_tool = session.pending_tool_call["client_tool"]
            return {
                "name": client_tool["name"],
                "params": client_tool.get("params") or {},
                "resumeToken": session.resume_token,
                "aiSessionIdentifier": session.pending_tool_call["ai_session_identifier"],
            }

        res.attr("clientToolRequest", value=get_pending_client_tool_request)

        res.attr("loop_state")
        res.attr("resume_token")

    def _get_session_config_rules(self):
        """If a config key is True, these values must also hold."""
        return {
            "enable_web_search": {
                "enable_resources_only": False,
            },
            "enable_resources_only": {
                "enable_web_search": False,
            },
        }

    def _set_pending_tool_call(self, pending_tool_call):
        """Set the pending tool call; the caller publishes the updated loop state."""
        self.pending_tool_call = pending_tool_call

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("agent_id"):
                agent = self.env["ai.agent"].browse(vals["agent_id"])
                vals["enable_web_search"] = not agent.restrict_to_sources
                vals["enable_resources_only"] = agent.restrict_to_sources
        return super().create(vals_list)

    def _get_related_record(self):
        self.ensure_one()
        if not (self.res_model and self.res_id):
            return None
        if not (record := self.env[self.res_model].browse(self.res_id)).exists():
            raise MissingError(self.env._("The record linked to the session was not found."))
        record = record.sudo(False)
        record.check_access('read')
        return record

    def _get_session_advance_unavailable_message(self):
        """Let optional addons stop a session advance when the browser context is unsuitable."""
        self.ensure_one()
        return False

    @api.model
    @api.model
    @api.model
    @api.model
    @api.model
    @api.model
    @api.model
    def _clean_session_state(self):
        """Disable the skills and tools the agent no longer owns"""
        for session in self:
            if not (state := session.state):
                continue
            skills = session.agent_id.skill_ids
            loaded_skills = state.get("loaded_skills", [])
            if not (skills_to_disable := [skill for skill in loaded_skills if skill not in skills.ids]):
                continue
            active_skills = skills.filtered(lambda skill: skill.id in loaded_skills)
            active_tools = (active_skills.tool_ids | session._get_session_default_tools()).ids
            tools_to_disable = [tool for tool in state["available_tools"] if tool not in active_tools]
            session.state = disable_skills(state, skills_to_disable, tools_to_disable)

    def get_session_config(self):
        return {
            "enable_web_search": self.enable_web_search,
            "enable_resources_only": self.enable_resources_only,
            "enable_think_longer": self.enable_think_longer,
            "auto_confirm": self.auto_confirm,
            "show_agent_steps": self.show_agent_steps,
        }

    def update_session_config(self, updated_config: dict):
        if "ai_prompt_button_ref" in updated_config:
            updated_config.pop("ai_prompt_button_ref")
        updated_config = self.validate_session_update(updated_config)
        self.write(updated_config)
        if "enable_web_search" in updated_config and (state := self.state):
            self._initialize_tool_state(state)
            self.state = state

        if "auto_confirm" in updated_config:
            if self.auto_confirm:
                message = self.env._("✅ Auto-approval enabled for this chat.")
            else:
                message = self.env._("⛔ Auto-approval deactivated.")
            self.turn_notifications = (self.turn_notifications or []) + [{'type': 'ai_note', 'body': message}]

        Store(bus_channel=self.channel_id).add(self, "_store_session_fields")

    def validate_session_update(self, updated_config: dict):
        session_config = self.get_session_config()
        valid_update_config = {}

        for key, value in updated_config.items():
            if key not in session_config:
                raise ValidationError(self.env._("Unrecognized AI session configuration key: %(key)s", key=key))
            if value != session_config[key]:
                valid_update_config[key] = value

        if not valid_update_config:
            return {}

        session_config.update(valid_update_config)
        validation_rules = self._get_session_config_rules()

        for key, rules in validation_rules.items():
            if not session_config.get(key):
                continue

            for dependent_key, expected_value in rules.items():
                if session_config.get(dependent_key) != expected_value:
                    raise ValidationError(self.env._("Can not enable %(key1)s and %(key2)s at the same time", key1=dependent_key, key2=key))

        return valid_update_config
