# Part of Odoo. See LICENSE file for full copyright and licensing details.
import logging
import json

from lxml import etree

from odoo import _
from odoo.http import request
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

# contains all valid operations
OPERATIONS_WHITELIST = [
    'add',
    'add_header_button',
    'attributes',
    'avatar_image',
    'buttonbox',
    'chatter',
    'kanban_colorpicker',
    'kanban_menu',
    'kanban_wrap_main',
    'map_popup_fields',
    'pivot_measures_fields',
    'graph_pivot_groupbys_fields',
    'move',
    'remove',
    'statusbar',
]


class StudioArchOperationsMixin:
    """ XPath operations applied to view architectures. """

    def _node_to_expr(self, node):
        if node.get('xpath_info'):
            expr_list = node.get('xpath_info')
            if node.get("subview_xpath"):
                # The first element of that list is the view's node
                # If we are editing a subview, this view's node is actually
                # targetted by subview_xpath, so let's remove it from the xpath_info
                expr_list = expr_list[1:]
            # Format of expr is /form/tag1[]/tag2[]/[...]/tag[]
            expr = ''.join(['/%s[%s]' % (parent['tag'], parent['indice']) for parent in expr_list])
        else:
            # Format of expr is //tag[@attr1_name=attr1_value][@attr2_name=attr2_value][...]
            expr = '//' + node['tag']
            for k, v in node.get('attrs', {}).items():
                if k == 'class':
                    # Special case for classes which usually contain multiple values
                    clx = v.strip().split(" ")
                    if clx:
                        str_classes = ",".join(f"'{cls}'" for cls in clx)
                        expr += f"[hasclass({str_classes})]"
                else:
                    expr += '[@%s=\'%s\']' % (k, v)

            # Avoid matching nodes in sub views.
            # Example with field as node:
            # A field should be defined only once in a view but in some cases,
            # a view can be composed by some other views where a field with
            # the same name may exist.
            # Here, we want to generate xpath based on the nodes in the parent view only.
            if not node.get('subview_xpath'):
                expr = expr + '[not(ancestor::field)]'

        # If we receive a more specific xpath because we are editing an inline
        # view, we add it in front of the generated xpath.
        if node.get('subview_xpath'):
            xpath = node.get('subview_xpath')
            if node.get('isSubviewAttr'):
                expr = xpath
            # Hack to check if the last subview xpath element is not the same than expr
            # E.g when we add a field in an empty subview list the expr computed
            # by studio will be only '/list' but this is useless since the
            # subview xpath already specify this element. So in this case,
            # we don't add the expr computed by studio.
            elif not xpath.endswith(expr):
                expr = xpath + expr
        return expr

    # Create a new xpath node based on an operation
    # TODO: rename it in master

    def _get_xpath_node(self, arch, operation):
        expr = self._node_to_expr(operation['target'])
        position = operation['position']

        return etree.SubElement(arch, 'xpath', {
            'expr': expr,
            'position': position
        })

    def _operation_remove(self, arch, operation, model=None):
        expr = self._node_to_expr(operation['target'])

        # We have to create a brand new xpath to remove this node from the view.
        etree.SubElement(arch, 'xpath', {
            'expr': expr,
            'position': 'replace'
        })
        # Sometimes, we have to delete more stuff than just a single tag. Those nodes
        # should be passed as a list in 'extra_nodes' key within the target node.
        if operation['target'].get('extra_nodes'):
            for target in operation['target']['extra_nodes']:
                expr = self._node_to_expr(target)
                etree.SubElement(arch, 'xpath', {
                    'expr': expr,
                    'position': 'replace'
                })

    def _operation_replace(self, arch, operation, model):
        """computes an xpath that will replace operation['target'] by operation['node'] in the arch"""
        target_expr = self._node_to_expr(operation['target'])

        replace_xpath = etree.SubElement(arch, 'xpath', {
            'expr': target_expr,
            'position': 'replace'
        })

        replace_with = operation['node']
        etree.SubElement(replace_xpath, replace_with['tag'], replace_with['attrs'])

    def _operation_add(self, arch, operation, model):
        node = operation['node']
        xpath_node = self._get_xpath_node(arch, operation)

        # Take a xml_node and put columns on it:
        # If the xml_node is not a group, this function will create a group node
        # to add two columns on it.
        def add_columns(xml_node):
            # Get the random key generated is JS.
            # Expected value: 'studio_<tag_name>_<random_key>
            name = 'studio_group_' + xml_node.get('name').split('_')[2]

            if xml_node.tag != 'group':
                xml_node_group = etree.SubElement(xml_node, 'group', {'name': name})
            else:
                xml_node_group = xml_node

            xml_node_page_left = etree.SubElement(xml_node_group, 'group', {'name': name + '_left'})
            xml_node_page_right = etree.SubElement(xml_node_group, 'group', {'name': name + '_right'})

        # Create the actual node inside the xpath. It needs to be the first
        # child of the xpath to respect the order in which they were added.
        xml_node = etree.Element(node['tag'], node.get('attrs'))
        if node['tag'] == 'notebook':
            name = 'studio_page_' + node['attrs']['name'].split('_')[2]
            xml_node_page = etree.Element('page', {'string': 'New Page', 'name': name})
            add_columns(xml_node_page)
            xml_node.insert(0, xml_node_page)
        elif node['tag'] == 'page':
            add_columns(xml_node)
        elif node['tag'] == 'group':
            if 'empty' not in operation:
                add_columns(xml_node)
        elif node['tag'] == 'button':
            # To create a stat button, we need
            #   - a many2one field (1) that points to this model
            #   - a field (2) that counts the number of records associated with the current record
            #   - an action to jump in (3) with the many2one field (1) as domain/context
            #
            # (1) [button_field] the many2one field
            # (2) [button_count_field] is a non-stored computed field (to always have the good value in the stat button, if access rights)
            # (3) [button_action] an act_window action to jump in the related model
            button_field = request.env['ir.model.fields'].browse(node['field'])
            button_count_field, button_action = self._get_or_create_fields_for_button(model, button_field, node['string'])

            # the XML looks like <button> <field/> </button : a element `field` needs to be inserted inside the button
            xml_node_field = etree.Element('field', {'widget': 'statinfo', 'name': button_count_field.name, 'string': node['string'] or button_count_field.field_description})
            xml_node.insert(0, xml_node_field)

            xml_node.attrib['type'] = 'action'
            xml_node.attrib['name'] = str(button_action.xml_id)
        else:
            xml_node.text = node.get('text')
        xpath_node.insert(0, xml_node)

    def _get_or_create_fields_for_button(self, model, field, button_name):
        """ Returns the button_count_field and the button_action link to a stat button.
            @param field: a many2one field
        """

        if (field.ttype != 'many2one' and field.ttype != 'many2many') or field.relation != model:
            raise UserError(_('The related field of a button has to be a many2one to %s.', model))

        model = request.env['ir.model']._get(model)

        # There is a counter on the button ; as the related field is a many2one, we need
        # to create a new computed field that counts the number of records in the one2many
        button_count_field_name = 'x_%s_%s_count' % (field.name, field.model.replace('.', '_'))[0:63]
        button_count_field = request.env['ir.model.fields'].search([('name', '=', button_count_field_name), ('model_id', '=', model.id)])
        if not button_count_field:
            compute_function = """
                    for record in self: record['%(count_field)s'] = self.env['%(model)s'].search_count([('%(field)s', '=', record.id)])
                """ % {
                    'model': field.model,
                    'field': field.name,
                    'count_field': button_count_field_name,
                }
            button_count_field = request.env['ir.model.fields'].with_context(studio=True).create({
                'name': button_count_field_name,
                'field_description': '%s count' % field.field_description,
                'model': model.model,
                'model_id': model.id,
                'ttype': 'integer',
                'store': False,
                'compute': compute_function.replace('    ', ''),  # remove indentation for safe_eval
            })

        # The action could already exist but we don't want to recreate one each time
        button_action_domain = "[('%s', '=', active_id)]" % (field.name)
        active_id = 'active_id' if field.ttype == 'many2one' else '[active_id]'
        button_action_context = "{'search_default_%s': active_id,'default_%s': %s}" % (field.name, field.name, active_id)
        button_action = request.env['ir.actions.act_window'].search([
            ('name', '=', button_name), ('res_model', '=', field.model),
            ('domain', '=', button_action_domain), ('context', '=', button_action_context),
        ])
        if not button_action:
            # Link the button with an associated act_window
            button_action = request.env['ir.actions.act_window'].with_context(studio=True).create({
                'name': button_name,
                'res_model': field.model,
                'view_mode': 'list,form',
                'domain': button_action_domain,
                'context': button_action_context,
            })

        return button_count_field, button_action

    def _operation_move(self, arch, operation, model=None):
        xpath_node = self._get_xpath_node(arch, operation)
        xml_node = etree.Element('xpath', {
            'expr': self._node_to_expr(operation['node']),
            'position': 'move',
        })
        xpath_node.append(xml_node)

    # Create or update node for each attribute

    def _operation_attributes(self, arch, operation, model=None):
        ir_model_data = request.env['ir.model.data']
        new_attrs = operation['new_attrs']

        if 'groups' in new_attrs:
            eval_attr = []
            group_ids = {}
            for many2many_value in new_attrs['groups']:
                if isinstance(many2many_value, str) and many2many_value.startswith("!"):
                    allow = False
                    _id = int(many2many_value[1:])
                else:
                    allow = True
                    _id = int(many2many_value)
                group_ids[_id] = allow

            if group_ids:
                xml_ids = {
                    imd["res_id"]: imd["complete_name"] for imd in ir_model_data.search_read([
                        ('model', '=', 'res.groups'),
                        ('res_id', 'in', list(group_ids.keys()))], ["res_id", "complete_name"]
                    )
                }

                for g_id, allow in group_ids.items():
                    if g_id not in xml_ids:
                        raise UserError(_(
                            "Only groups with an external ID can be used here. Please choose another "
                            "group or assign manually an external ID to this group."
                        ))
                    group_attr = xml_ids[g_id]
                    if not allow:
                        group_attr = "!" + group_attr

                    eval_attr.append(group_attr)
            eval_attr = ",".join(eval_attr)
            new_attrs['groups'] = eval_attr

        if new_attrs.get('type') and operation['target']['tag'] == 'button':
            # Set an empty name value for the button
            new_attrs['name'] = ''
        xpath_node = self._get_xpath_node(arch, operation)

        for key, new_attr in new_attrs.items():
            xml_node = etree.Element('attribute', {'name': key})
            if new_attr is not None:
                xml_node.text = json.dumps(new_attr) if isinstance(new_attr, bool) else str(new_attr)
            xpath_node.insert(0, xml_node)

            # change the field description when changing the field label (for custom fields)
            if key == 'string' and operation.get('node', {}).get('tag') == 'field':
                field_name = operation.get('node', {}).get('attrs', {}).get('name')
                field_id = request.env['ir.model.fields'].search([('model', '=', model), ('name', '=', field_name)])
                if field_id and field_id._is_manual_name(field_name) and field_id.field_description != new_attr:
                    field_id.write({'field_description': new_attr})

    def _operation_buttonbox(self, arch, operation, model=None):
        studio_view_arch = arch  # The actual arch is the studio view arch
        # Get the arch of the form view with inherited views applied
        arch = request.env[model].with_context(studio=True, no_address_format=True).get_view(view_type='form')['arch']
        parser = etree.XMLParser(remove_blank_text=True)
        arch = etree.fromstring(arch, parser=parser)

        # Create xpath to put the buttonbox as the first child of the sheet
        if arch.find('sheet'):
            sheet_node = arch.find('sheet')
            if list(sheet_node):
                # Check if children exists
                xpath_node = etree.SubElement(studio_view_arch, 'xpath', {
                    'expr': '//sheet/*[1]',
                    'position': 'before'
                })
            else:
                xpath_node = etree.SubElement(studio_view_arch, 'xpath', {
                    'expr': '//sheet',
                    'position': 'inside'
                })
            # Create and insert the buttonbox node inside the xpath node
            buttonbox_node = etree.Element('div', {'name': 'button_box', 'class': 'oe_button_box'})
            xpath_node.append(buttonbox_node)

    def _operation_add_header_button(self, arch, operation, model):
        """Add action button for form, list or kanban view"""
        actions_for_model = self.get_actions_for_model(model)
        type = 'action' if len(actions_for_model) > 0 else 'object'
        params = {'string': 'New Button', 'type': type}
        expression = "//header[1]"
        position = "inside"
        xpath_node = arch.find('xpath[@expr="{expr}"][@position="{position}"]'.format(expr=expression, position=position))
        if xpath_node is None:
            xpath_node = etree.SubElement(arch, 'xpath', {
                'expr': expression,
                'position': position,
            })

        statusbarbutton = etree.Element('button', params)
        xpath_node.append(statusbarbutton)

    def _operation_chatter(self, arch, operation, model=None):
        def _get_remove_field_op(arch, field_name):
            return {
                'type': 'remove',
                'target': {
                    'tag': 'field',
                    'attrs': {
                        'name': field_name,
                    },
                }
            }

        Model = request.env[operation['model']]
        if not (Model._custom or isinstance(Model, request.env.registry['mail.thread'])):
            # Chatter can only be activated form models that (can) inherit from mail.thread
            return

        # From this point, the model is either a custom model or inherits from mail.thread
        model = request.env['ir.model']._get(operation['model'])
        if model.state == 'manual' and not model.is_mail_thread:
            # Activate mail.thread inheritance on the custom model
            model.write({'is_mail_thread': True})
        if model.state == 'manual' and not model.is_mail_activity:
            # Activate mail.activity inheritance on the custom model
            model.write({'is_mail_activity': True})

        # Remove message_ids, activity_ids and message_follower_ids if already defined in form view
        if operation['remove_message_ids']:
            self._operation_remove(arch, _get_remove_field_op(arch, 'message_ids'))
        if operation['remove_follower_ids']:
            self._operation_remove(arch, _get_remove_field_op(arch, 'message_follower_ids'))
        if operation['remove_activity_ids']:
            self._operation_remove(arch, _get_remove_field_op(arch, 'activity_ids'))

        xpath_node = etree.SubElement(arch, 'xpath', {
            'expr': '//sheet',
            'position': 'after',
        })
        chatter_node = etree.Element('chatter')
        xpath_node.append(chatter_node)

    def _operation_kanban_wrap_main(self, arch, operation, model):
        wrap_type = operation.get('wrap_type')
        # we must copy the content of the card under the <main> node
        main_node = etree.fromstring("<t t-name='card'><main>$0</main></t>")
        etree.SubElement(arch, 'xpath', {
            'expr': '//t[@t-name="card"]',
            'position': 'replace',
            'mode': 'outer'
        }).append(main_node)
        if wrap_type == "aside":
            xpath_node = etree.SubElement(arch, 'xpath', {
                'expr': '//t[@t-name="card"]',
                'position': 'attributes'
                })
            attribute_node = etree.Element('attribute', name='class')
            attribute_node.text = "row g-0"
            xpath_node.append(attribute_node)
            xpath_node_main = etree.SubElement(arch, 'xpath', {
                'expr': '//main',
                'position': 'attributes'
                })
            attribute_node_main = etree.Element('attribute', name='class')
            attribute_node_main.text = "col-10"
            xpath_node_main.append(attribute_node_main)
        # results in a t[@t-name="card"]/main/t[@t-name="card"] template
        # we must remove the latest t-name value
        xpath_node = etree.SubElement(arch, 'xpath', {
            'expr': '//main/t[@t-name="card"]',
            'position': 'attributes'
            })
        xpath_node.append(etree.Element('attribute', name='t-name'))

    def _operation_kanban_colorpicker(self, arch, operation, model):
        """ Insert a colorpicker under a kanban menu.
        """
        view_id = operation.get('view_id')
        view = request.env['ir.ui.view'].browse(view_id)
        base_view = etree.fromstring(view.get_combined_arch())

        color_field = base_view.get("highlight_color")
        if color_field is None:
            # create a field if no one is set as color attribute
            model_id = request.env['ir.model']._get_id(model)
            if not model_id:
                return

            color_field = 'x_color'
            if not request.env['ir.model.fields'].search_count([('model_id', '=', model_id), ('name', '=', color_field), ('ttype', '=', 'integer')], limit=1):
                request.env['ir.model.fields'].create({
                    'model': model,
                    'model_id': model_id,
                    'name': color_field,
                    'field_description': 'Card color',
                    'ttype': 'integer',
                })
            etree.SubElement(arch, 'xpath', {
                'expr': '//kanban',
                'position': 'attributes',
            }).append(etree.fromstring(f"<attribute name='highlight_color'>{color_field}</attribute>"))

        etree.SubElement(arch, 'xpath', {
            'expr': './/t[@t-name="menu"]',
            'position': 'inside',
        }).append(etree.fromstring(f"<field name='{color_field}' widget='kanban_color_picker'></field>"))

    def _operation_kanban_menu(self, arch, operation, model):
        """ Insert a menu in a kanban view arch."""
        menu_node = etree.fromstring("""
            <t t-name="menu">
                <t t-if="widget.editable"><a type="open" class="dropdown-item">Edit</a></t>
                <t t-if="widget.deletable"><a type="delete" class="dropdown-item">Delete</a></t>
            </t>
        """)
        etree.SubElement(arch, 'xpath', {
            'expr': '//t[@t-name="card"]',
            'position': 'before',
        }).append(menu_node)

    def _operation_avatar_image(self, arch, operation, model):
        studio_view_arch = arch  # The actual arch is the studio view arch
        arch = request.env[model].with_context(studio=True, no_address_format=True).get_view(view_type='form')['arch']
        parser = etree.XMLParser(remove_blank_text=True)
        arch = etree.fromstring(arch, parser=parser)

        model_id = request.env['ir.model']._get_id(model)
        IrModelFields = request.env['ir.model.fields']

        if not model_id:
            raise UserError(_('The model %s does not exist.', model))
        if operation.get('field'):
            field_id = IrModelFields.search([
                ('model', '=', model),
                ('name', '=', operation['field'])
            ])
            if not field_id:
                raise UserError(_('The field %s does not exist.', operation['field']))
        else:
            field_id = IrModelFields.search([
                ('model_id', '=', model_id),
                ('name', '=', 'x_avatar_image'),
                ('ttype', '=', 'binary')
            ])
            # create a field selection x_avatar_image if it doesn't exist in the model
            if not field_id:
                field_id = IrModelFields.with_context(studio=True).create({
                    'model': model,
                    'model_id': model_id,
                    'name': 'x_avatar_image',
                    'field_description': 'Avatar',
                    'ttype': 'binary',
                })
        attrs = {
            'expr': '//div[hasclass("oe_title")]',
            'position': 'before',
        }
        hasFlexH1 = arch.xpath("//div[hasclass('oe_title')]//h1[hasclass('d-flex')]") and True
        if hasFlexH1:
            attrs.update({
                "expr": "//div[hasclass('oe_title')]//h1[hasclass('d-flex')]",
                "position": "inside",
            })
        avatar_class = "oe_avatar ml-3 h4" if hasFlexH1 else "oe_avatar ml-3 mr-3"
        etree.SubElement(studio_view_arch, 'xpath', attrs).append(
            etree.fromstring("""
                <field name="%s" widget="image" class="%s"/>
            """ % (field_id.name, avatar_class))
        )

    def _operation_statusbar(self, arch, operation, model=None):
        """ Create and insert a header as the first child of the element. """
        xpath_node = etree.SubElement(arch, 'xpath', {
            'expr': '//form[1]/*[1] | //list[1]/*[1] | //kanban[1]/*[1]',
            'position': 'before'
        })
        xpath_node.append(etree.Element('header'))

    def _operation_map_popup_fields(self, arch, operation, model):
        fields = request.env['ir.model.fields'].browse(operation['target']['field_ids'])
        for field in fields:
            if operation['target']['operation_type'] == 'add':
                op = {
                    'node': {
                        'tag': 'field',
                        'attrs': {
                            'name': field.name,
                            'string': field.field_description,
                        }
                    },
                    'target': {
                        'tag': 'map',
                    },
                    'position': 'inside',
                }
                self._operation_add(arch, op, model)
            else:
                op = {
                    'type': 'remove',
                    'target': {
                        'tag': 'field',
                        'attrs': {
                            'name': field.name,
                        },
                    }
                }
                self._operation_remove(arch, op)

    def _operation_pivot_measures_fields(self, arch, operation, model):
        fields = request.env['ir.model.fields'].browse(operation['target']['field_ids'])
        for field in fields:
            if operation['target']['operation_type'] == 'add':
                op = {
                    'node': {
                        'tag': 'field',
                        'attrs': {
                            'name': field.name,
                            'type': 'measure',
                        }
                    },
                    'target': {
                        'tag': 'pivot',
                    },
                    'position': 'inside',
                }
                self._operation_add(arch, op, model)
            else:
                op = {
                    'type': 'remove',
                    'target': {
                        'tag': 'field',
                        'attrs': {
                            'name': field.name,
                        },
                    }
                }
                self._operation_remove(arch, op)

    def _operation_graph_pivot_groupbys_fields(self, arch, operation, model):
        fieldsName = request.env['ir.model.fields'].search([
            ('name', 'in', operation['target']['field_names']),
            ('model', '=', model),])
        for field in fieldsName:
            if operation['target']['operation_type'] == 'add':
                op = {
                    'node': {
                        'tag': 'field',
                        'attrs': {
                            'name': field.name,
                            'type': operation['target']['field_type'],
                        }
                    },
                    'target': {
                        'tag': operation['target']['view_type'],
                    },
                    'position': 'inside',
                }
                self._operation_add(arch, op, model)
            elif operation['target']['operation_type'] == 'replace':
                op = {
                    'node': {
                        'tag': 'field',
                        'attrs': {
                            'name': field.name,
                            'type': operation['target']['field_type'],
                        }
                    },
                    'target': {
                        'tag': 'field',
                        'attrs': {
                            'name': operation['target']['old_field_names'],
                        },
                    },
                }
                self._operation_replace(arch, op, model)
            else:
                op = {
                    'type': 'remove',
                    'target': {
                        'tag': 'field',
                        'attrs': {
                            'name': field.name,
                        },
                    }
                }
                self._operation_remove(arch, op)
