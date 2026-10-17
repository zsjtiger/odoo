# Part of Odoo. See LICENSE file for full copyright and licensing details.
"""Previews shown to the user before the AI changes records."""
import ast
from collections import defaultdict

from markupsafe import Markup

from odoo.api import Environment
from odoo.fields import Command
from odoo.models import BaseModel
from odoo.tools.mail import html_to_inner_content
from odoo.tools.misc import format_date, format_datetime

from .ai_utils import UserInputResponse


def make_confirmation_request_preview(env, body):
    return {
        'type': 'confirmation',
        'body': body,
        'choices': [
            {'label': env._("Yes, do it"), 'value': UserInputResponse.CONFIRM_ONCE},
            {'label': env._("Yes, always approve in this chat"), 'value': UserInputResponse.AUTO_CONFIRM},
            {'label': env._("No, I want something else"), 'value': UserInputResponse.DECLINE},
        ],
        'allow_free_text': False,
    }


def make_records_update_preview(records, changes):
    env = records.env
    fnames = changes.keys()
    new_rec = records[0].new(changes, origin=records[0])
    new_vals = new_rec.read(fnames)[0]
    old_vals = records.read(fnames)[0]

    items = []
    for fname in fnames:
        field = records._fields[fname]
        if field.readonly:
            raise ValueError(f"Field {fname} is readonly and cannot be updated. Try to update another field")
        if field.type in ('binary', 'image', 'properties'):
            raise ValueError(f"Field of type {field.type} cannot be updated ({fname})")
        if field.type in ('many2many', 'one2many'):
            val = _make_x2m_preview_value(env, field, changes[fname])
        elif field.type in ('html', 'text'):
            if field.type == "html":
                old_vals[fname] = html_to_inner_content(old_vals[fname])
                new_vals[fname] = html_to_inner_content(new_vals[fname])
            # only crop the previous val as the user needs to see the whole new value to approve it
            if old_vals[fname] and len(old_vals[fname]) > 120:
                old_vals[fname] = old_vals[fname][:50] + "..." + old_vals[fname][-50:]
            val = new_vals[fname]
        elif field.type == 'many2one':
            old_vals[fname] = records[0][fname].display_name
            val = new_rec[fname].display_name
        elif field.type == 'date':
            old_vals[fname] = format_date(env, old_vals[fname])
            val = format_date(env, new_vals[fname])
        elif field.type == 'datetime':
            old_vals[fname] = format_datetime(env, old_vals[fname])
            val = format_datetime(env, new_vals[fname])
        elif field.type == 'selection':
            old_vals[fname] = field._selection.get(old_vals[fname])
            val = field._selection.get(new_vals[fname])
        else:
            val = new_vals[fname]

        item = {
            'field_name': field.string,
            'new_val': val if val not in (False, None) else env._("None"),
        }
        if not (
            field.type in ('one2many', 'many2many') or
            len(records) > 1 and len(records.mapped(fname)) > 1 or
            fname == records._rec_name
        ):
            item['old_val'] = old_vals[fname] if old_vals[fname] not in (False, None) else env._("None")
        items.append(item)
    return items


def _make_x2m_preview_value(env, field, commands):
    """Describe the ORM commands of a x2many update as the list of changes shown to the user."""
    if not isinstance(commands, list) or not isinstance(commands[0], tuple):
        raise ValueError(f"{field.name} is a x2many and expects a Command as value. Try again with a Command")
    cmd_items = []
    comodel = _get_comodel(env, field)
    for cmd in commands:
        if cmd[0] in (Command.CREATE, Command.UPDATE, Command.DELETE):
            raise ValueError(f"Command {cmd[0]} cannot be used during an update.")
        if cmd[0] == Command.UNLINK:
            cmd_items.append(env._(
                'Remove "%(record_name)s"',
                record_name=Markup("<i>%s</i>") % comodel.browse(cmd[1]).display_name,
            ))
        elif cmd[0] == Command.LINK:
            cmd_items.append(env._(
                'Add "%(record_name)s"',
                record_name=Markup("<i>%s</i>") % comodel.browse(cmd[1]).display_name,
            ))
        elif cmd[0] == Command.CLEAR:
            cmd_items.append(env._("Remove all"))
        elif cmd[0] == Command.SET:
            cmd_items.append(env._(
                "Replace all by %(new_relations)s",
                new_relations=Markup("<ul>%s</ul>") % Markup().join(
                    Markup("<li>%s</li>") % rec.display_name
                    for rec in comodel.browse(cmd[2])
                )
            ))
    if len(cmd_items) > 1:
        return Markup("<ul>%s</ul>") % Markup().join(Markup("<li>%s</li>") % i for i in cmd_items)
    if cmd_items:
        return cmd_items[0]
    return ""


def make_batch_update_preview(env, explanation, updates):
    if len(updates) > 50:
        raise ValueError("Max 50 updates at a time are authorized")

    def _get_update_preview(update):
        model_name = update['model_name']
        domain = update['domain']
        changes_data = update['changes']
        changes = {c['field']: ast.literal_eval(c['x2m_commands']) if c.get('x2m_commands') else c.get('value') for c in changes_data}

        if (model := env.get(model_name)) is None:
            raise ValueError(f"Model {model_name} does not exists")

        # sudo(False) just in case the tool ever gets run in a sudo-ed env (shouldn't happen)
        model = model.sudo(False)
        parsed_domain = env['ai.tool']._parse_domain(model_name, domain, operation='write')
        if parsed_domain in (True, []):
            raise ValueError("You cannot update using a dummy truthy domain (e.g. [], True). To update all records, pass a domain that matches all records instead.")
        records = model.search(parsed_domain)
        records.check_access('write')

        if not records:
            return None

        if len(records) == 1:
            if records._name == env.context.get('active_model') and records.id == env.context.get('active_id'):
                label = env._("Current record")
            else:
                label = Markup('%s "%s"') % (records._description, Markup("<i>%s</i>") % records.display_name)
        else:
            label = env._("%(nb_records)s records (%(record_model)s)",
                nb_records=len(records),
                record_model=records._description
            )

        return {
            'label': label,
            'items': make_records_update_preview(records, changes),
        }

    sections = [p for u in updates if (p := _get_update_preview(u))]
    if not sections:
        raise ValueError("No records matched the given domain. Try again with another domain")

    return env['ir.qweb']._render('ai.ai_records_preview', {"template": "update", "explanation": explanation, 'sections': sections})


def make_create_preview(env: Environment, explanation: str, model_name: str, preview_data: list[dict]):
    def _get_create_preview(record_info: dict):
        field_values_data = record_info["field_values"]
        vals = {
            c["field"]: c.get("x2m_link_ids") if c.get("x2m_link_ids") else c.get("value")
            for c in field_values_data
        }

        model: BaseModel = env.get(model_name)
        model = model.sudo(False)
        if model is None:
            raise ValueError(f"Model {model_name} does not exists")
        model.check_access("create")

        return make_record_create_preview(model, vals)

    preview_per_model = defaultdict(list)
    for record_info in preview_data:
        if p := _get_create_preview(record_info):
            preview_per_model[model_name].append({"label": env.get(model_name)._description, "items": p})

    sections = []
    for model_name, preview_items in preview_per_model.items():
        for index, preview in enumerate(preview_items):
            if len(preview_items) > 1:
                preview["label"] = f"{preview['label']} {index + 1}"
            sections.append(preview)

    return env["ir.qweb"]._render(
        "ai.ai_records_preview",
        {"template": "create", "explanation": explanation, "sections": sections},
    )


def _get_comodel(env, field):
    comodel = env[field.comodel_name]
    if field.comodel_name == "ir.model":
        comodel = comodel.sudo()
    return comodel


def make_record_create_preview(model: BaseModel, vals: dict):
    fields = []
    for key, val in vals.items():
        if not val:
            continue
        field = model._fields[key]
        formatted_value = val
        if field.type == "date":
            formatted_value = format_date(model.env, val)
        elif field.type == "datetime":
            formatted_value = format_datetime(model.env, val)
        elif field.type in ["html", "text"]:
            formatted_value = val
            if field.type == "html":
                formatted_value = html_to_inner_content(val)
            if formatted_value and len(formatted_value) > 120:
                formatted_value = formatted_value[:50] + "..." + formatted_value[-50:]
        elif field.type == "one2many":
            comodel = _get_comodel(model.env, field)
            cmd_items = []
            index = 1

            def get_label(i: int) -> Markup:
                return Markup("<b>%s %d</b>") % (comodel._description, i)

            if isinstance(val, int):
                cmd_items.append(
                    {
                        "label": get_label(index),
                        "value": Markup('<i>"%s"</i> (existing)') % comodel.browse(val).display_name,
                    }
                )
            elif isinstance(val, list):
                for record in comodel.browse(val):
                    cmd_items.append(
                        {
                            "label": get_label(index),
                            "value": Markup('<i>"%s"</i> (existing)') % record.display_name,
                        }
                    )
                    index += 1
            index += 1
            formatted_value = cmd_items
        elif field.type == "many2many":
            comodel = _get_comodel(model.env, field)
            cmd_items = []
            link_cmd_items: list[str] = []
            if isinstance(val, int):
                link_cmd_items.append(
                    Markup("<i>%s</i>")
                    % comodel.browse(val).display_name,
                )
            elif isinstance(val, list):
                for record in comodel.browse(val):
                    link_cmd_items.append(Markup("<i>%s</i>") % record.display_name)
            if link_cmd_items:
                cmd_items.append({"label": model.env._("Add"), "value": Markup(", ").join(link_cmd_items)})
            formatted_value = cmd_items
        elif field.type == "many2one":
            comodel = _get_comodel(model.env, field)
            formatted_value = comodel.browse(val).display_name
        fields.append({"label": field.string, "value": formatted_value})
    return fields
