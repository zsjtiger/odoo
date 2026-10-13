"""The base model and the unknown model: the extensions of the models that every model inherits from."""

from __future__ import annotations

from odoo import models


class Base(models.AbstractModel):
    """ The base model, which is implicitly inherited by all models. """
    _name = 'base'
    _description = 'Base'


class Unknown(models.AbstractModel):
    """
    Abstract model used as a substitute for relational fields with an unknown
    comodel.
    """
    _name = '_unknown'
    _description = 'Unknown'
