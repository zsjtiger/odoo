# Part of Odoo. See LICENSE file for full copyright and licensing details.
"""Layout of addons/web/static/src: where each file and folder goes.

Used by setup/move_web_files.py, which moves the files and rewrites the
references to them, both in this repository and in other addons (--port).
Paths are relative to addons/web/static/src.
"""

GROUPS = {
    # root files and transitional folders
    'boot': ['main.js', 'start.js', 'env.js', 'session.js', 'module_loader.js', 'service_worker.js', 'polyfills'],
    # core
    'core/framework': ['core/assets.js', 'core/registry.js', 'core/registry_hook.js', 'core/services.js', 'core/templates.js',
                       'core/template_inheritance.js', 'core/lazy_component.js', 'core/main_components_container.js',
                       'core/legacy_service_starter.js', 'core/macro.js', 'core/transition.js'],
    'core/services': ['core/browser', 'core/commands', 'core/debug', 'core/debug_mode_plugin.js', 'core/effects', 'core/errors',
                      'core/field_service.js', 'core/global_bus_plugin.js', 'core/hotkeys', 'core/install_scoped_app',
                      'core/name_service.js', 'core/network', 'core/notifications', 'core/offline', 'core/orm_plugin.js',
                      'core/pwa', 'core/session', 'core/ui', 'core/user.js', 'core/user_switch'],
    'core/data': ['core/context.js', 'core/currency.js', 'core/domain.js', 'core/l10n', 'core/py_js'],
    'core/components': ['core/action_swiper', 'core/autocomplete', 'core/avatar', 'core/badge', 'core/barcode', 'core/bottom_sheet',
                        'core/btn_circle', 'core/checkbox', 'core/code_editor', 'core/colorlist', 'core/colors', 'core/copy_button',
                        'core/datetime', 'core/dropdown', 'core/dropzone', 'core/emoji_picker', 'core/file_input', 'core/file_upload',
                        'core/file_viewer', 'core/navigation', 'core/notebook', 'core/overlay', 'core/pager', 'core/phone',
                        'core/popover', 'core/position', 'core/resizable_panel', 'core/select_menu', 'core/signature',
                        'core/tags_list', 'core/time_picker', 'core/tooltip'],
    'core/dialogs': ['core/dialog', 'core/confirmation_dialog', 'core/notification_alert_dialog', 'core/permission_prompt_dialog',
                     'core/domain_selector_dialog', 'core/expression_editor_dialog'],
    'core/editors': ['core/domain_selector', 'core/expression_editor', 'core/tree_editor', 'core/model_field_selector',
                     'core/model_selector', 'core/record_selectors', 'core/ir_ui_view_code_editor'],
    'core/utils': ['core/anchor_scroll_prevention.js', 'core/crypto.js', 'core/virtual_grid_hook.js'],
    # field widgets
    'views/fields/text': ['char', 'text', 'email', 'phone', 'url', 'password', 'copy_clipboard', 'html', 'json', 'ace',
                          'ir_ui_view_ace', 'iframe_wrapper', 'translation'],
    'views/fields/numeric': ['integer', 'float', 'float_factor', 'float_time', 'float_time_tz', 'float_toggle', 'monetary',
                             'percentage', 'percent_pie', 'progress_bar', 'gauge'],
    'views/fields/boolean': ['boolean', 'boolean_checkbox', 'boolean_favorite', 'boolean_icon', 'boolean_toggle'],
    'views/fields/date': ['datetime', 'relative_date', 'timezone_mismatch'],
    'views/fields/selection': ['selection', 'radio', 'priority', 'statusbar', 'state_selection', 'badge', 'badges_selection',
                               'label_selection', 'color', 'color_picker', 'kanban_color_picker'],
    'views/fields/relational': ['many2one', 'many2one_avatar', 'many2one_barcode', 'many2one_binary', 'many2one_reference',
                                'many2one_reference_integer', 'many2many_binary', 'many2many_checkboxes', 'many2many_tags',
                                'many2many_tags_avatar', 'many2many_tags_color_dot', 'many2x_binary', 'badges_many2one',
                                'x2many', 'reference'],
    'views/fields/media': ['image', 'image_url', 'binary', 'attachment_image', 'contact_image', 'pdf_viewer', 'signature',
                           'google_slide_viewer'],
    'views/fields/special': ['domain', 'field_selector', 'properties', 'handle', 'stat_info', 'contact_statistics',
                             'additional_identifiers', 'journal_dashboard_graph', 'json_checkboxes'],
    # scss
    'scss/bootstrap': ['scss/import_bootstrap.scss', 'scss/bootstrap_overridden.scss', 'scss/bootstrap_overridden_frontend.scss',
                       'scss/bootstrap_review.scss', 'scss/bootstrap_review_backend.scss', 'scss/bootstrap_review_frontend.scss',
                       'scss/bs_mixins_overrides.scss', 'scss/bs_mixins_overrides_backend.scss', 'scss/utilities_custom.scss',
                       'scss/utilities_custom_backend.scss'],
    'scss/variables': ['scss/pre_variables.scss', 'scss/primary_variables.scss', 'scss/primary_variables_print.scss',
                       'scss/secondary_variables.scss'],
}
# single moves, renaming the folder
RENAMES = {
    'owl2': 'core/owl',
    'webclient/settings_form_view': 'views/settings',
    'webclient/res_user_group_ids_field': 'views/fields/relational/res_user_group_ids',
}


# the steps of the reorganization, applied one at a time
PHASES = {
    'W1': lambda target: target.startswith('boot/') or target == 'core/owl',
    'W2': lambda target: target.startswith('core/'),
    'W3': lambda target: target.startswith('views/'),
    'W4': lambda target: target.startswith('scss/'),
}


def moves(phase=None):
    """Return {old path: new path} of the given phase (all of them if None)."""
    result = {}
    for target, items in GROUPS.items():
        for item in items:
            old = f'views/fields/{item}' if target.startswith('views/fields/') else item
            result[old] = f'{target}/{old.rsplit("/", 1)[-1]}'
    result.update(RENAMES)
    if phase is None:
        return result
    done = set()
    for name, belongs in PHASES.items():
        selected = {old: new for old, new in result.items() if belongs(new) and old not in done}
        if name == phase:
            return selected
        done |= set(selected)
    raise ValueError(f'unknown phase {phase!r}')
