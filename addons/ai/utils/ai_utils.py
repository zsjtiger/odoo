# Part of Odoo. See LICENSE file for full copyright and licensing details.
import enum
import json
import re
from typing import Any

from markupsafe import Markup

from odoo.fields import Binary, Image
from odoo.tools.json import json_default

from .ai_image_tools import field_to_image_path
from .types import AIMessageParts
from odoo.addons.ai.llm import client_from_params

AI_MODELS_BLOCKLIST = {
    'base.automation',
    'res.device',
    'res.groups',
    'res.groups.privilege',
    'res.users.settings',
}


def is_ai_internal_model(model_name):
    return model_name.startswith('ai.')


def get_llm_client(env):
    """Return the OpenAI-compatible client configured for this database."""
    return client_from_params(env['ir.config_parameter'].sudo().get_str)


def get_ai_int_param(env, key, default):
    """Return the integer value of the AI config parameter ``key``, or ``default`` when unset.

    The parameter is read with sudo because the tool execution path runs as the end user.
    """
    return env['ir.config_parameter'].sudo().get_int(key, default)


class UserInputResponse(enum.StrEnum):
    """Pre-defined response values for user input requests."""
    CONFIRM_ONCE = 'confirm_once'
    AUTO_CONFIRM = 'auto_confirm'
    DECLINE = 'decline'


def is_ai_parts(obj: Any) -> bool:
    if not isinstance(obj, list):
        return False
    for part in obj:
        if not isinstance(part, dict):
            return False
        if part.get('type') not in ('text', 'inline_data'):
            return False
        if part['type'] == 'text' and 'text' not in part:
            return False
        if part['type'] == 'inline_data' and ('mimetype' not in part or 'data' not in part):
            return False
    return True


def format_tool_result(tool_call, result=None, error=None):
    if not is_ai_parts(result):
        if error is not None:
            text = f"Error: {error}"
        elif result is None:
            text = 'success'
        elif not isinstance(result, str):
            text = json.dumps(result, default=json_default, ensure_ascii=False)
        else:
            text = result
        result = [{
            'type': 'text',
            'text': text,
        }]
    return {
        'tool_name': tool_call['name'],
        'tool_call_id': tool_call['call_id'],
        'result': result,
        'success': error is None,
    }


def format_tool_summary(summary, tool_call):
    # add call_id if there are args to show, to show caret in ui only if there's st to load
    data_id = ''
    if tool_call['args'].keys() - {'tool_status', '__final_message', 'explanation'}:
        data_id = Markup('data-id="%s"') % tool_call['call_id']
    return Markup('<div class="o-ai-tool-summary" %s><i class="oi oi-fw me-1" data-icon="%s"/>%s</div>') % (
        data_id,
        summary.get('icon', 'build'),
        summary.get('text'),
    )


def get_text_from_parts(parts: AIMessageParts) -> Any:
    """
    Extracts the text from the parts.
    :param parts: AIMessageParts
    :return: - an empty string if no text parts are found
            - the content of the text part if only one text part is found. The content can be a string, a list, a dict or any JSON compatible format.
            - the combined text from the parts if multiple text parts are found. In such case, the combination logic is only defined if all parts are simple strings.
    """
    all_text = [part['text'] for part in parts if part['type'] == 'text']
    return all_text[0] if len(all_text) == 1 else "\n".join(all_text)


def enable_tools(tool_context: dict, tool_ids: list[int]):
    state = tool_context["state"]
    state["available_tools"] = list(dict.fromkeys(state.get("available_tools", []) + tool_ids))


def enable_skills(tool_context: dict, skill_ids: list[int], tool_ids: list[int]):
    state = tool_context["state"]
    state["loaded_skills"] = list(dict.fromkeys(state.get("loaded_skills", []) + skill_ids))
    enable_tools(tool_context, tool_ids)


def disable_skills(state: dict, skill_ids: list[int], tool_ids: list[int] = ()):
    state = dict(state)
    state["loaded_skills"] = [skill for skill in state["loaded_skills"] if skill not in skill_ids]
    state["available_tools"] = [tool for tool in state["available_tools"] if tool not in tool_ids]
    return state


def split_binary_fields(model, fnames):
    """Split the fields to read from the binary ones."""
    read_fnames = []
    binary_fields = {}
    for fname in fnames or model.fields_get(attributes=()):
        field = model._fields.get(fname)
        if isinstance(field, Binary):
            model.check_field_access(field, 'read')
            binary_fields[fname] = field
        else:
            read_fnames.append(fname)
    return read_fnames or ['id'], binary_fields


def add_binary_references(model, vals_list, binary_fields):
    """Add a reference to each unread binary field"""
    records = model.browse([vals['id'] for vals in vals_list])
    attachments = {
        (attachment.res_field, attachment.res_id): attachment
        for attachment in model.env['ir.attachment']._get_field_attachments(
            records, [fname for fname, field in binary_fields.items() if field.attachment]
        )
    }
    for fname, field in binary_fields.items():
        if field.attachment:
            metadata_by_id = {
                record.id: (attachment.name, attachment.mimetype, attachment.file_size)
                for record in records
                if (attachment := attachments.get((fname, record.id)))
            }
        elif field.store or field.related:
            records.fetch([fname])
            metadata_by_id = {
                record.id: (value.filename, value.mimetype, value.size)
                for record in records
                if (value := record[fname])
            }
        else:
            metadata_by_id = dict.fromkeys(records.ids, (None, None, None))

        is_image = isinstance(field, Image)
        for record, vals in zip(records, vals_list):
            if (metadata := metadata_by_id.get(record.id)) is None:
                vals[fname] = False
                continue
            name, mimetype, size = metadata
            reference = {'is_binary': True}
            if size is not None:
                reference['size'] = size
            if name:
                reference['name'] = name
            if mimetype:
                reference['mimetype'] = mimetype
            if is_image:
                reference['image_path'] = field_to_image_path(record, fname)
            vals[fname] = reference


def format_name_to_llm(name: str):
    # Formats a name to be used as a tool name with LLMs.
    # For a server action called "AI: Create Leads", it returns "ai_create_leads"
    return re.sub(r'[^a-z0-9]+', '_', name.lower()).strip('_')[:64] or "tool"
