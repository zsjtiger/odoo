# -*- coding: utf-8 -*-
"""What the mobile client can render. Studio (web_builder) reads this to offer only supported controls.

The lists mirror the frontend registries; tests/test_mobile_capabilities.py fails when they drift apart.
"""
from odoo import api, models

# names registered with mobileFieldRegistry.add(...) (static/src/fields)
FIELD_WIDGETS = (
    'badge', 'badges_selection', 'binary', 'boolean', 'boolean_toggle', 'cascade', 'char', 'char_voice',
    'color', 'date', 'datetime', 'email', 'fallback', 'float', 'float_time', 'float_toggle', 'gps', 'handle',
    'html', 'image', 'image_url', 'integer', 'json', 'label_selection', 'many2many', 'many2many_checkboxes',
    'many2many_tags', 'many2many_tags_avatar', 'many2one', 'many2one_avatar', 'monetary', 'one2many',
    'one2many_form', 'password', 'percentage', 'phone', 'priority', 'progressbar', 'radio', 'reference',
    'selection', 'state_selection', 'statusbar', 'text', 'text_voice', 'timeline', 'url',
)

# names registered with mobileViewRegistry.add(...) (static/src/views)
VIEW_TYPES = ('calendar', 'form', 'kanban', 'list')

# tags of a form layout that the mobile form renders (static/src/views/form/layout.js)
FORM_TAGS = ('field', 'notebook', 'page', 'separator', 'group')

# Studio field types (ir.model.fields.ttype) the mobile client shows; the others fall back to read-only text
SUPPORTED_FIELD_TYPES = (
    'char', 'text', 'html', 'integer', 'float', 'monetary', 'boolean', 'date', 'datetime',
    'selection', 'many2one', 'many2many', 'one2many', 'binary', 'image',
)

# relational fields whose lookup honours the field domain on mobile; the others ignore it
DOMAIN_FIELD_TYPES = ('many2one',)


class MobileCapabilities(models.AbstractModel):
    _name = 'mobile.capabilities'
    _description = 'Mobile client capabilities'

    @api.model
    def get_capabilities(self):
        from .mobile_page import get_sprite_icon_ids  # local import: the sprite is read from disk
        return {
            'field_widgets': list(FIELD_WIDGETS),
            'view_types': list(VIEW_TYPES),
            'form_tags': list(FORM_TAGS),
            'supported_field_types': list(SUPPORTED_FIELD_TYPES),
            'domain_field_types': list(DOMAIN_FIELD_TYPES),
            'icons': sorted(get_sprite_icon_ids()),
        }
