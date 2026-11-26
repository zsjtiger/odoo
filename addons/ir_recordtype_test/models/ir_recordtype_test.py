# -*- coding: utf-8 -*-
from odoo import fields, models


class IrRecordtypeTestRecord(models.Model):
    """Model used by the tests only: declares record types with the framework flag."""
    _name = 'ir.recordtype.test'
    _description = 'Record Type Test Model'
    _record_type = True

    name = fields.Char()
