# Part of Odoo. See LICENSE file for full copyright and licensing details.
import logging


from odoo import http, _
from odoo.http import request
from odoo.exceptions import UserError
from odoo.fields import Domain

_logger = logging.getLogger(__name__)


class StudioActionsMixin:
    """ Studio actions, apps, menus and background images. """

    @http.route('/web_builder/get_studio_action', type='jsonrpc', auth='user')
    def get_studio_action(self, action_name, model, view_id=None, view_type=None):
        model = request.env['ir.model']._get(model)

        action = None
        if hasattr(self, '_get_studio_action_' + action_name):
            action = getattr(self, '_get_studio_action_' + action_name)(model, view_id=view_id, view_type=view_type)
            if action:
                action["context"] = action.get("context", {})
                action["context"]["studio"] = 1

        return action

    def _get_studio_action_access(self, model, **kwargs):
        return {
            'name': _('Access Records'),
            'type': 'ir.actions.act_window',
            'res_model': 'ir.access',
            'views': [[False, 'list'], [False, 'form']],
            'target': 'current',
            'domain': [],
            'context': {
                'default_model_id': model.id,
                'search_default_model_id': model.id,
            },
            'help': _("""<p class="o_view_nocontent_smiling_face">
                Add a new access record
            </p>
            """),
        }

    def _get_studio_action_automation_webhooks(self, model, **kwargs):
        action = request.env['ir.actions.act_window']._for_xml_id('web_builder.webhook_automation_act')
        action['context'] = {
            'default_model_id': model.id,
            'search_default_model_id': model.id,
            'active_test': False,
            'default_trigger': "on_webhook",
        }
        return action

    def _get_studio_action_automations(self, model, **kwargs):
        action = request.env['ir.actions.act_window']._for_xml_id('base_automation.base_automation_act')
        action['context'] = {
            'default_model_id': model.id,
            'search_default_model_id': model.id,
            'active_test': False,
        }
        return action

    def _get_studio_action_filters(self, model, **kwargs):
        return {
            'name': _('Filter Rules'),
            'type': 'ir.actions.act_window',
            'res_model': 'ir.filters',
            'views': [[False, 'list'], [False, 'form']],
            'target': 'current',
            'domain': [],
            'context': {  # model_id is a Selection on ir.filters
                'default_model_id': model.model,
                'search_default_model_id': model.model,
            },
            'help': _(""" <p class="o_view_nocontent_smiling_face">
                Add a new filter
            </p>
            """),
        }

    def _get_studio_action_reports(self, model, **kwargs):
        report_name_blacklist = [
            "account_followup.report_followup_print_all",
            "stock.report_lot_label",
            "stock.report_picking_type_label",
            "product.report_producttemplatelabel2x7",
            "product.report_producttemplatelabel4x7",
            "product.report_producttemplatelabel4x12",
            "product.report_producttemplatelabel4x12noprice",
            "product.report_producttemplatelabel_dymo",
            "stock.report_reception_report_label",
            "mrp.label_production_view_pdf",
            "delivery_iot.report_shipping_labels",
            "delivery_iot.report_shipping_docs",
            "l10n_co_reports.report_libro_diario",
            "account.report_original_vendor_bill",
        ]
        report_domain = Domain.AND([
            # One can edit only reports backed by persisting models
            [("model_id.transient", "=", False)],
            [("model_id.abstract", "=", False)],
            [("report_type", "not in", ['qweb-text'])],
            [("report_name", "not in", report_name_blacklist)],
            [("model", "=", model.model)]
        ])
        return {
            'name': _('Reports for %(model_name)s (%(model)s)', model_name=model.name, model=model.model),
            'type': 'ir.actions.act_window',
            'res_model': 'ir.actions.report',
            'views': [[False, 'kanban'], [False, 'form']],
            'target': 'current',
            'domain': report_domain,
            'context': {
                'default_model': model.model,
            },
            'help': _(""" <p class="o_view_nocontent_empty_report">
                Add a new report
            </p>
            """),
        }

    def _get_studio_action_actions_server(self, model, **kwargs):
        return {
            'name': _('Actions Server'),
            'type': 'ir.actions.act_window',
            'res_model': 'ir.actions.server',
            'views': [[False, 'list'], [False, "form"]],
            'target': 'current',
            'context': {
                'web_builder.auto_add_to_context': True,
                'default_model_id': model.id,
                'search_default_model_id': model.id,
                'search_default_action_type': True,  # auto groupby action.state
            },
            'help': _("""<p>
                Create a new Server Action to enhance the power of the model.
            </p>
            """),
        }

    @http.route('/web_builder/create_new_app', type='jsonrpc', auth='user')
    def create_new_app(self, app_name=False, menu_name=False, model_choice=False, model_id=False, model_options=False, icon=None, context=None):
        """Create a new app @app_name, linked to a new action associated to the model_id or the newlyy created model.
            @param menu_name: name of the first menu (and model if model_choice is 'new') of the app
            @param model_choice: 'new' for a new model, 'existing' for an existing model selected in the wizard
            @param model_id: the model which will be associated to the action if menu_choice is 'existing'
            @param model_options: dictionary of options for the model to be created to include some behaviours OoB
                (e.g. archiving, messaging, etc.)
            @param icon: the icon of the new app.
                It can either be:
                 - the ir.attachment id of the uploaded image
                 - if the icon has been created, an array containing: [icon_class, color, background_color]
        """
        if context:
            request.update_context(**context)
        request.update_context(studio=1)
        _logger.info('creating new app "%s" with main menu "%s"', app_name, menu_name)
        if model_choice == 'existing' and model_id:
            model = request.env['ir.model'].browse(model_id)
            extra_models = request.env['ir.model']
            _logger.info('using existing model %s as main model, all main views duplicated for use in the new app', model.model)
        elif model_choice == 'new' and menu_name:
            # create a new model
            (model, extra_models) = request.env['ir.model'].studio_model_create(menu_name, options=model_options)
            _logger.info('created new model %s as main model with the following options: %s', model.model, ','.join(model_options))
        else:
            _logger.error('inconsistent parameters: model_choice is %s, model_id is %s and menu_name(model) is %s', model_choice, model_id, menu_name)
            raise UserError(_("If you don't want to create a new model, an existing model should be selected."))

        action = model._create_default_action(menu_name)
        action_ref = 'ir.actions.act_window,' + str(action.id)

        # create the menus (app menu + first submenu)
        menu_values = {
            'name': app_name,
        }
        child_menu_vals = [(0, 0, {'name': menu_name,'action': action_ref})]

        # check if a configuration menu is needed
        if extra_models:
            configuration_menu_vals = {'name': _('Configuration'), 'child_id': [], 'is_studio_configuration': True, 'sequence': 100}
            for extra_model in extra_models:
                extra_action = extra_model._create_default_action(extra_model.name)
                configuration_menu_vals['child_id'].append((0, 0, {'name': extra_model.name, 'action': 'ir.actions.act_window,'+ str(extra_action.id)}))
            child_menu_vals.append((0, 0, configuration_menu_vals))

        menu_values.update(self._get_icon_fields(icon))
        menu_values['child_id'] = child_menu_vals

        new_menu = request.env['ir.ui.menu'].with_context(studio=True).create(menu_values)

        return {
            'menu_id': new_menu.id,
            'action_id': action.id,
        }

    @http.route('/web_builder/create_new_menu', type='jsonrpc', auth='user')
    def create_new_menu(self, menu_name=False, model_choice=False, model_id=False, model_options=False, parent_menu_id=None, context=None):
        """ Create a new menu @menu_name, linked to a new action associated to the model_id
            @param model_choice: 'new' for a new model, 'existing' for an existing model selected in the wizard
            @param model_id: the model which will be associated to the action if menu_choice is 'existing'
            @param model_options: dictionary of options for the model to be created to include some behaviours OoB
                (e.g. archiving, messaging, etc.)
            @param parent_menu_id: the parent of the new menu.
        """
        if context:
            request.update_context(**context)
        request.update_context(studio=1)
        sequence = 10
        if parent_menu_id:
            menu = request.env['ir.ui.menu'].search_read([('parent_id', '=', parent_menu_id)], fields=['sequence'], order='sequence desc', limit=1)
            if menu:
                sequence = menu[0]['sequence'] + 1

        _logger.info('creating new menu "%s"', menu_name)
        if model_choice == 'existing' and model_id:
            model = request.env['ir.model'].browse(model_id)
            extra_models = request.env['ir.model']
            _logger.info('using existing model %s, all main views duplicated for use in the new app', model.model)
        elif model_choice == 'new' and menu_name:
            # create a new model
            (model, extra_models) = request.env['ir.model'].studio_model_create(menu_name, options=model_options)
            _logger.info('created new model %s with the following options: %s', model.model, ','.join(model_options))
        elif model_choice == 'parent':
            (model, extra_models) = (None, None)
        else:
            _logger.error('inconsistent parameters: model_choice is %s, model_id is %s and menu_name(model) is %s', model_choice, model_id, menu_name)
            raise UserError(_("If you don't want to create a new model, an existing model should be selected."))

        # create the action
        if model:
            action = model._create_default_action(menu_name)
            action_ref = 'ir.actions.act_window,' + str(action.id)
        else:
            action = request.env.ref('base.action_open_website')
            action_ref = 'ir.actions.act_url,' + str(action.id)

        # create the submenu
        new_menu = request.env['ir.ui.menu'].with_context(studio=True).create({
            'name': menu_name,
            'action': action_ref,
            'parent_id': parent_menu_id,
            'sequence': sequence,
        })

        # create extra menus for configuration of extra models (tags, stages)
        if extra_models:
            config_menu = new_menu._get_studio_configuration_menu()
            child_menu_vals = list()
            for extra_model in extra_models:
                views = request.env['ir.ui.view'].search([('model', '=', extra_model.model)])
                extra_action = extra_model._create_default_action(extra_model.name)
                child_menu_vals.append((0, 0, {'name': extra_model.name, 'action': 'ir.actions.act_window,'+ str(extra_action.id)}))
            config_menu.write({'child_id': child_menu_vals})
        return {
            'menu_id': new_menu.id,
            'action_id': action.id,
        }

    @http.route('/web_builder/edit_menu_icon', type='jsonrpc', auth='user')
    def edit_menu_icon(self, menu_id, icon, context=None):
        if context:
            request.update_context(**context)
        values = self._get_icon_fields(icon)
        request.env['ir.ui.menu'].browse(menu_id).write(values)

    def _get_icon_fields(self, icon):
        """ Get icon related fields (depending on the @icon received). """
        if isinstance(icon, int):
            icon_id = request.env['ir.attachment'].browse(icon)
            if not icon_id:
                raise UserError(_('The icon is not linked to an attachment'))
            return {'web_icon_data': icon_id.raw.to_base64()}
        elif isinstance(icon, list) and len(icon) == 3:
            return {'web_icon': ','.join(icon)}
        else:
            raise UserError(_('The icon has not a correct format'))

    @http.route('/web_builder/set_background_image', type='jsonrpc', auth='user')
    def set_background_image(self, attachment_id, context=None):
        if context:
            request.update_context(**context)
        attachment = request.env['ir.attachment'].browse(attachment_id)
        if attachment:
            request.env.company.background_image = attachment.raw

    @http.route('/web_builder/reset_background_image', type='jsonrpc', auth='user')
    def reset_background_image(self, context=None):
        if context:
            request.update_context(**context)
        if request.env.company in request.env.user.with_user(request.env.uid).company_ids:
            request.env.company.background_image = None

    @http.route('/web_builder/add_view_type', type='jsonrpc', auth='user')
    def add_view_type(self, action_type, action_id, res_model, view_type, args, context=None):
        if context:
            request.update_context(**context)

        if view_type == 'activity':
            model = request.env['ir.model']._get(res_model)
            if model.state == 'manual' and not model.is_mail_activity:
                # Activate mail.activity.mixin inheritance on the custom model
                model.write({'is_mail_activity': True})

        try:
            request.env[res_model].with_context(no_address_format=True).get_view(view_type=view_type)
        except UserError:
            return False
        self.edit_action(action_type, action_id, args)
        return True

    @http.route('/web_builder/edit_action', type='jsonrpc', auth='user')
    def edit_action(self, action_type, action_id, args):

        action_id = request.env[action_type].browse(action_id)
        if action_id:
            if 'view_mode' in args:
                # As view_id and view_ids have precedence on view_mode, we need to correctly set them
                if action_id.view_id or action_id.view_ids:
                    view_modes = args['view_mode'].split(',')

                    # add new view_mode
                    missing_view_modes = [x for x in view_modes if x not in [y.view_mode for y in action_id.view_ids]]
                    for view_mode in missing_view_modes:
                        vals = {
                            'act_window_id': action_id.id,
                            'view_mode': view_mode,
                        }
                        if action_id.view_id and action_id.view_id.type == view_mode:
                            # reuse the same view_id in the corresponding view_ids record
                            vals['view_id'] = action_id.view_id.id

                        request.env['ir.actions.act_window.view'].with_context(studio=True).create(vals)

                    for view_id in action_id.view_ids:
                        if view_id.view_mode in view_modes:
                            # resequence according to new view_modes
                            view_id.sequence = view_modes.index(view_id.view_mode)
                        else:
                            # remove old view_mode
                            view_id.unlink()

            action_id.write(args)

        return True

    @http.route('/web_builder/get_actions_for_model', type='jsonrpc', auth='user')
    def get_actions_for_model(self, model):
        actions_list = {}
        # first get all actions that are available in the Cog menu
        actions_for_model = request.env["ir.actions.actions"].search([
            ('binding_model_id', '=', model)
        ])
        # the following code groups action_ids by type to avoid having a browse call for each action
        actions_types = {}
        for action in actions_for_model:
            actions_types.setdefault(action.type, []).append(action.id)
        for action_type, action_ids in actions_types.items():
            actions = request.env[action_type].browse(action_ids)
            for action in actions:
                actions_list[action.id] = {
                    'name': action.display_name,
                    'xml_id': action.xml_id or action.id
                }

        # also list server actions that are not available in the Cog menu
        server_actions_for_model = request.env["ir.actions.server"].search([
            ('model_id', '=', model),
            ('binding_model_id', '=', False)
        ])
        for action in server_actions_for_model:
            actions_list[action.id] = {
                'name': action.display_name,
                'xml_id': action.xml_id
            }
        return actions_list
