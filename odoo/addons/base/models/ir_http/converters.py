# Part of Odoo. See LICENSE file for full copyright and licensing details.
# ----------------------------------------------------------
# ir_http routing converters
# ----------------------------------------------------------
import werkzeug.routing

from odoo import api, models
from odoo.http import request

try:
    from werkzeug.routing import NumberConverter
except ImportError:
    from werkzeug.routing.converters import NumberConverter  # moved in werkzeug 2.2.2


class RequestUID:
    def __init__(self, **kw):
        self.__dict__.update(kw)


class ModelConverter(werkzeug.routing.BaseConverter):
    regex = r'[0-9]+'

    def __init__(self, url_map, model=False):
        super().__init__(url_map)
        self.model = model

    def to_python(self, value: str) -> models.BaseModel:
        uid = RequestUID(value=value, converter=self)
        env = api.Environment(request.env.cr, uid, request.env.context)
        unslug = env['ir.http']._unslug
        return env[self.model].browse(unslug(value)[1])

    def to_url(self, value: models.BaseModel) -> str:
        return value.env['ir.http']._slug(value)


class ModelsConverter(werkzeug.routing.BaseConverter):
    regex = r'[0-9,]+'

    def __init__(self, url_map, model=False):
        super().__init__(url_map)
        self.model = model

    def to_python(self, value: str) -> models.BaseModel:
        uid = RequestUID(value=value, converter=self)
        env = api.Environment(request.env.cr, uid, request.env.context)
        return env[self.model].browse(int(v) for v in value.split(','))

    def to_url(self, value: models.BaseModel) -> str:
        return ",".join(value.ids)


class SignedIntConverter(NumberConverter):
    regex = r'-?\d+'
    num_convert = int
