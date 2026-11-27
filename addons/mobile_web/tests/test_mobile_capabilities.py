# -*- coding: utf-8 -*-
import re
from pathlib import Path

from odoo.tests import TransactionCase, tagged

from odoo.addons.mobile_web.models import mobile_capabilities as caps

SRC = Path(caps.__file__).resolve().parents[1] / 'static' / 'src'


def _registered(folder, registry):
    names = set()
    for path in (SRC / folder).rglob('*.js'):
        text = path.read_text(encoding='utf-8', errors='ignore')
        names |= set(re.findall(registry + r'\.add\(\s*"([^"]+)"', text))
    return names


@tagged('post_install', '-at_install')
class TestMobileCapabilities(TransactionCase):

    def test_field_widgets_match_the_frontend_registry(self):
        self.assertEqual(set(caps.FIELD_WIDGETS), _registered('fields', 'mobileFieldRegistry'))

    def test_view_types_match_the_frontend_registry(self):
        self.assertEqual(set(caps.VIEW_TYPES), _registered('views', 'mobileViewRegistry'))

    def test_capabilities_are_served(self):
        info = self.env['mobile.capabilities'].get_capabilities()
        self.assertIn('many2one', info['field_widgets'])
        self.assertIn('form', info['view_types'])
        self.assertTrue(info['icons'])
