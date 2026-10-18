# Part of Odoo. See LICENSE file for full copyright and licensing details.
import logging

from ast import literal_eval
from copy import deepcopy
from lxml import etree
from itertools import chain

from odoo import http
from odoo.http import request
from odoo.exceptions import ValidationError
from odoo.tools import clean_context

from .arch_operations import OPERATIONS_WHITELIST

_logger = logging.getLogger(__name__)


class StudioViewsMixin:
    """ Studio view architecture: read, write, restore and inline views. """

    def _get_studio_view(self, view):
        view = view._get_closest_primary_view()
        domain = [('inherit_id', '=', view.id), ('name', '=', self._generate_studio_view_name(view))]
        return view.search(domain, order='priority desc, name desc, id desc', limit=1)

    def _set_studio_view(self, view, arch):
        studio_view = self._get_studio_view(view)
        if studio_view and len(arch):
            studio_view.arch_db = arch
            return studio_view
        elif studio_view:
            studio_view.unlink()
        elif len(arch):
            return self._create_studio_view(view, arch)

    def _generate_studio_view_name(self, view):
        return "Odoo Studio: %s customization" % (view.name)

    @http.route('/web_studio/get_studio_view_arch', type='jsonrpc', auth='user')
    def get_studio_view_arch(self, model, view_type, view_id=False, context=None):
        if context:
            request.update_context(**context)

        if not view_id:
            # TOFIX: it's possibly not the used view ; see fields_get_view
            # try to find the lowest priority matching ir.ui.view
            view_id = request.env['ir.ui.view'].default_view(request.env[model]._name, view_type)
        # We have to create a view with the default view if we want to customize it.
        ir_model = request.env['ir.model']._get(model)
        view = ir_model._get_default_view(view_type, view_id)
        studio_view = self._get_studio_view(view)

        return {
            'studio_view_id': studio_view and studio_view.id or False,
            'studio_view_arch': studio_view and studio_view.arch_db or "<data/>",
            'main_view_id': view.id,
        }

    def _return_view(self, view, studio_view, context=None):
        if context is None:
            context = {}

        ViewModel = request.env[view.model]
        fields_view = ViewModel.with_context(dict(context, studio=True, no_address_format=True)).get_view(view.id, view.type)
        view_type = view.type
        models = fields_view['models']

        return {
            'views': {view_type: fields_view},
            'studio_view_id': studio_view.id,
            'models': {model: {"fields": request.env[model].fields_get()} for model in models}
        }

    @http.route('/web_studio/restore_default_view', type='jsonrpc', auth='user')
    def restore_default_view(self, view_id):
        view = request.env['ir.ui.view'].browse(view_id)
        self._set_studio_view(view, "")

        studio_view = self._get_studio_view(view)

        return self._return_view(view, studio_view)

    @http.route('/web_studio/edit_view', type='jsonrpc', auth='user')
    def edit_view(self, view_id, studio_view_arch, operations=None, model=None, context=None):
        if context:
            context_cleaned = clean_context(context)
            request.update_context(**context_cleaned)
        IrModelFields = request.env['ir.model.fields']
        view = request.env['ir.ui.view'].browse(view_id)._get_closest_primary_view()
        operations = operations or []
        for op in operations:
            if op['type'] not in OPERATIONS_WHITELIST:
                raise ValidationError(request.env._('The operation  type "%s" is not supported', op['type']))
        parser = etree.XMLParser(remove_blank_text=True)
        if studio_view_arch == "":
            studio_view_arch = '<data/>'
        arch = etree.fromstring(studio_view_arch, parser=parser)
        model = model or view.model

        # Determine whether an operation is associated with
        # the creation of a binary field
        def create_binary_field(op):
            node = op.get('node')
            if node and node.get('tag') == 'field' and node.get('field_description'):
                ttype = node['field_description'].get('type')
                is_image = node['attrs'].get('widget') == 'image'
                is_signature = node['attrs'].get('widget') == 'signature'
                return ttype == 'binary' and not is_image and not is_signature
            return False

        def is_monetary(op):
            node = op.get('node')
            if node and node.get('tag') and node.get('field_description'):
                ttype = node['field_description'].get('type')
                return ttype == 'monetary'
            return node and node.get('attrs') and ('currency_field' in node.get('attrs'))

        # Every time the creation of a binary field is requested,
        # we also create an invisible char field meant to contain the filename.
        # The char field is then associated with the binary field
        # via the 'filename' attribute of the latter.
        # Do it in another list to keep the order of the operations
        # otherwise, the "append" of the filemane binary would be misplaced
        _operations = []
        for op in operations:
            _operations.append(op)
            if not create_binary_field(op):
                continue
            bin_file_field_name = op['node']['field_description']['name']
            filename = bin_file_field_name + '_filename'

            # Create an operation adding an additional char field
            char_op = deepcopy(op)
            char_op['node']['field_description'].update({
                'name': filename,
                'type': 'char',
                'field_description': request.env._('Filename for %s', op['node']['field_description']['name']),
                'string': f"{bin_file_field_name} Filename",
            })
            node = op.get('node')
            if node and node.get('tag') == 'field' and node.get('field_description') and node['field_description'].get('related'):
                model_name = node['field_description'].get("model_name") or model
                related_filename = node['field_description']['related'] + '_filename'
                related_model_path = related_filename.split(".")[:-1]
                related_filename = request.env["ir.model.fields"]._get_related_field(model_name, related_filename)
                if not related_filename:
                    continue
                path = ".".join(chain(related_model_path, [related_filename.name]))
                char_op['node']['field_description'].update({'related': path})
            char_op['node']['attrs']['invisible'] = 'True'

            # put the filename field after the binary field
            char_op['target']['xpath_info'] = None
            char_op['target']['tag'] = 'field'
            char_op['target']['attrs'] = {'name': bin_file_field_name}
            char_op['target']['position'] = 'after'
            char_op['position'] = 'after'

            _operations.append(char_op)

            op['node']['attrs']['filename'] = filename

        # CREATE CURRENCY FIELD
        operations = _operations
        _operations = []

        for op in operations:
            if not is_monetary(op):
                _operations.append(op)
                continue
            new_field = op['node'].get('field_description')
            values = op['node'].get('field_description') or op['node']['attrs']
            currency_op = deepcopy(op)

            current_currency_field = new_field and new_field.get("currency_field")
            if new_field and not current_currency_field:
                # There is no currencies in the model, create one with the operation
                currency_op['node']['field_description'].update({
                    'name': 'x_studio_currency_id',
                    'type': 'many2one',
                    'relation': 'res.currency',
                    'field_description': 'Currency',
                })
                currency_op['node']['field_description'].pop("string", None)

                if related := new_field.get("related"):
                    model_name = new_field.get("model_name") or model
                    related_monetary = request.env["ir.model.fields"]._get_related_field(model_name, related)
                    related_model_path = related.split(".")[:-1]
                    related_currency = related_monetary and related_monetary.get_currency_field(request.env[related_monetary.model_name])
                    if related_currency:
                        if not related_model_path:
                            # The monetary is related to the current model (no dots, no following links)
                            # The currency on current model should exist and we just have to add it to the view
                            new_field['currency_field'] = related_currency
                            currency_op["node"] = {"tag": "field", "attrs": {"name": related_currency}}
                            current_currency_field = related_currency
                        else:
                            to_model = request.env[related_monetary.model_name]
                            related_currency = to_model._fields[related_currency]
                            path = ".".join(chain(related_model_path, [related_currency.name]))
                            currency_op['node']['field_description']["related"] = path
                            currency_op['node']['field_description']["store"] = False
                            new_related_field_name = path.replace(".", "_")
                            currency_op['node']['field_description']["name"] = f"x_studio_{new_related_field_name}"
                            currency_op['node']['field_description']['field_description'] = f"{request.env['ir.model']._get(to_model._name).name} {related_currency.get_description(self.env, 'string')['string']}"
                            current_currency_field = currency_op['node']['field_description']["name"]

                if not current_currency_field:
                    # delete the 'related' attribute from currency if it comes from a related monetary
                    currency_op['node']['field_description']["store"] = True
                    currency_op['node']['field_description'].pop("related", None)
                    current_currency_field = currency_op['node']['field_description']["name"]

                new_field['currency_field'] = current_currency_field
            else:
                # There is a currency in the model, set it up to eventually add it to the arch
                currency_op['node'].pop('field_description', None)
                currency_op['node']['attrs'] = {'name': values['currency_field']}

            if not values.get('currency_in_view'):
                # The currency field is not in the arch, add it
                _operations.append(currency_op)

            if op['node'].get('attrs', {}).get('currency_field'):
                # When monetary field already exist, the client put the currency infos in attrs
                del op['node']['attrs']['currency_field']
                del op['node']['attrs']['currency_in_view']
            _operations.append(op)

        operations = _operations
        for op in operations:
            model_name = model
            # create a new field if it does not exist
            if 'node' in op:
                if op['node'].get('tag') == 'field' and op['node'].get('field_description'):
                    special = op['node']['field_description'].get('special')
                    model_name = op['node']['field_description'].get("model_name") or model_name
                    is_special_lines = special == 'lines'
                    # Check if field exists before creation
                    field = IrModelFields.search([
                        ('name', '=', op['node']['field_description']['name']),
                        ('model', '=', model_name),
                    ], limit=1)

                    if not field:
                        if is_special_lines:
                            field = request.env['ir.model']._get(model_name)._setup_one2many_lines(
                                op['node']['field_description']['name'])
                        elif relation_model := op['node']['field_description'].get("relation_id"):
                            if not isinstance(relation_model, int):
                                field_type = op['node']['field_description']["type"]
                                new_model = request.env["ir.model"]._quick_create_model(
                                    model_values=relation_model,
                                    parent_field_type=field_type
                                )
                                if field_type == "many2one":
                                    op['node']['field_description']["group_expand"] = op['node']['field_description'].get("group_expand", True)
                                op['node']['field_description']["relation_id"] = new_model.id
                        field = field or self.create_new_field(op['node']['field_description'])

                    op['node']['attrs']['name'] = field.name
                    if field.ttype == "many2one" and op["type"] == "add":
                        create_name_field = request.env.registry[field.relation]._rec_name

                        # Parse all the options
                        options = literal_eval(op['node']['attrs'].get('options', '{}'))
                        if create_name_field and create_name_field != "name":
                            options['create_name_field'] = create_name_field
                            op['node']['attrs']['options'] = str(options)

                if op['node'].get('tag') == 'filter' and op['node']['attrs'].get('create_group'):
                    op['node']['attrs'].pop('create_group')
                    create_group_op = {
                        'node': {
                            'tag': 'group',
                            'attrs': {
                                'name': 'studio_group_by',
                            }
                        },
                        'empty': True,
                        'target': {
                            'tag': 'search',
                        },
                        'position': 'inside',
                    }
                    self._operation_add(arch, create_group_op, model)
            # set a more specific xpath (with templates//) for the kanban view
            if view.type == 'kanban':
                if op.get('target') and op['target'].get('tag') == 'field':
                    op['target']['tag'] = 'templates//field'
                    if op['target'].get('extra_nodes'):
                        for target in op['target']['extra_nodes']:
                            target['tag'] = 'templates//' + target['tag']

            # call the right operation handler
            getattr(self, '_operation_%s' % (op['type']))(arch, op, model)

        new_arch = etree.tostring(arch, encoding='unicode', pretty_print=True)
        studio_view = self._get_studio_view(view)
        try:
            # Normalize the new arch
            normalized_view = (studio_view or view).normalize(new_arch)
            studio_view = self._set_studio_view(view, normalized_view)
        except ValidationError:  # Element '<...>' cannot be located in parent view
            # If the studio view is not applicable after normalization, let's
            # just ignore the normalization step, it's better to have a studio
            # view that is not optimized than to prevent the user from making
            # the change he would like to make.
            studio_view = self._set_studio_view(view, new_arch)

        return self._return_view(view, studio_view or request.env["ir.ui.view"], context)

    def _create_studio_view(self, view, arch):
        view = view._get_closest_primary_view()
        # We have to play with priorities in order for our customization to be the last
        # to be applied.
        # In studio, what the user sees is the resulting view from all the inheritance.
        # Hence if the user does something it is on that result. To apply what they wanted, we need
        # to set the customization as last.
        priority = max(view.inherit_children_ids.mapped("priority"), default=0) * 10
        default_prio = view._fields["priority"].default(view)
        if priority <= default_prio:
            priority = 99
        return request.env['ir.ui.view'].with_context(studio=True).create({
            'type': view.type,
            'model': view.model,
            'inherit_id': view.id,
            'mode': 'extension',
            'priority': priority,
            'arch': arch,
            'name': self._generate_studio_view_name(view),
        })

    @http.route('/web_studio/edit_view_arch', type='jsonrpc', auth='user')
    def edit_view_arch(self, view_id, view_arch, context=None):
        if context:
            context_cleaned = clean_context(context)
            request.update_context(**context_cleaned)
        # view is really the view on which we are writing the new arch verbatim (in most cases, the studio view)
        # the _return_view API calls get_views, that will eventually return the whole arch
        # meaning that even if we pass the studio view, we'll get the full arch with
        # the studio view applied on it.
        view = request.env['ir.ui.view'].browse(view_id)
        if view:
            view.write({'arch': view_arch})
            ViewModel = request.env[view.model]
            studio_view = self._get_studio_view(view)
            return self._return_view(view, studio_view, context)

    @http.route('/web_studio/edit_page_layout', type='jsonrpc', auth='user')
    def edit_page_layout(self, view_id, arch, context=None):
        """ Stores the arch of a page layout as the studio view of the form, verbatim.

            The arch replaces the root of the form (it is not merged through the
            operations of the view editor), so it is written as it is.
        """
        if context:
            request.update_context(**clean_context(context))
        view = request.env['ir.ui.view'].browse(view_id)._get_closest_primary_view()
        studio_view = self._set_studio_view(view, arch)
        return self._return_view(view, studio_view or request.env['ir.ui.view'], context)

    @http.route('/web_studio/create_default_view', type='jsonrpc', auth='user')
    def create_default_view(self, model, view_type, attrs):
        attrs['string'] = "Default %s view for %s" % (view_type, model)
        arch = self._get_default_view(view_type, attrs)
        request.env['ir.ui.view'].with_context(studio=True).create({
            'type': view_type,
            'model': model,
            'arch': arch,
            'name': attrs['string'],
        })

    def _get_default_view(self, view_type, attrs):
        arch = etree.Element(view_type, attrs)
        return etree.tostring(arch, encoding='unicode', pretty_print=True, method='html')

    @http.route('/web_studio/create_inline_view', type='jsonrpc', auth='user')
    def create_inline_view(self, model, view_id, field_name, subview_type, subview_xpath, context=None):
        # Forward context to forward `_view_ref` keys
        # e.g. `test_enter_x2many_edition_and_add_field`
        if context:
            request.update_context(**context)
        view = request.env['ir.ui.view'].browse(view_id)
        studio_view = self._get_studio_view(view)
        if not studio_view:
            studio_view = self._create_studio_view(view, '<data/>')
        parser = etree.XMLParser(remove_blank_text=True)
        arch = etree.fromstring(studio_view.arch_db, parser=parser)
        position = 'inside'
        xpath_node = arch.find('xpath[@expr="%s"][@position="%s"]' % (subview_xpath, position))
        if xpath_node is None:  # bool(node) == False if node has no children
            xpath_node = etree.SubElement(arch, 'xpath', {
                'expr': subview_xpath,
                'position': position
            })
        view_arch, _ = request.env[model].with_context(no_address_format=True)._get_view(view_type=subview_type)
        xml_node = self._inline_view_filter_nodes(view_arch)
        xpath_node.insert(0, xml_node)
        studio_view.arch_db = etree.tostring(arch, encoding='utf-8', pretty_print=True)
        return studio_view.arch_db

    def _inline_view_filter_nodes(self, inline_view_etree):
        """
        Filters out from a standard view some nodes that are
        irrelevant in an inline view (like the chatter)

        @param {Etree} inline_view_etree: the arch of the view
        @return {Etree}
        """
        unwanted_xpath = [
            "//chatter",
            "*[hasclass('o_attachment_preview')]",
        ]
        for path in unwanted_xpath:
            for node in inline_view_etree.xpath(path):
                inline_view_etree.remove(node)

        return inline_view_etree
