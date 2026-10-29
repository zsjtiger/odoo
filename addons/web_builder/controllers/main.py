# Part of Odoo. See LICENSE file for full copyright and licensing details.
from odoo import http

from .actions import StudioActionsMixin
from .approval import StudioApprovalMixin
from .arch_operations import StudioArchOperationsMixin
from .fields import StudioFieldsMixin
from .views import StudioViewsMixin


class WebStudioController(StudioActionsMixin, StudioFieldsMixin, StudioViewsMixin,
                          StudioArchOperationsMixin, StudioApprovalMixin, http.Controller):
    """ Routes of the Studio client: each feature area is implemented in a mixin module. """
