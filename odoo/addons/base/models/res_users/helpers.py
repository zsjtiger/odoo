"""The helpers of the users: the logger, the identity check and the helpers of the values."""

from __future__ import annotations

import logging
import json
import time
from functools import wraps
from itertools import chain
from odoo import _
from odoo.exceptions import UserError
from odoo.http import request

_logger = logging.getLogger('odoo.addons.base.models.res_users')


NO_GROUP_CHANGE_LOG = object()


concat = chain.from_iterable


def _jsonable(o):
    try: json.dumps(o)
    except TypeError: return False
    else: return True


def check_identity(fn):
    """ Wrapped method should be an *action method* (called from a button
    type=object), and requires extra security to be executed. This decorator
    checks if the identity (password) has been checked in the last 10mn, and
    pops up an identity check wizard if not.

    Prevents access outside of interactive contexts (aka with a request)
    """
    @wraps(fn)
    def wrapped(self, *args, **kwargs):
        if not request:
            raise UserError(_("This method can only be accessed over HTTP"))

        if request.session.get('identity-check-last', 0) > time.time() - 10 * 60:
            # update identity-check-last like github?
            return fn(self, *args, **kwargs)

        w = self.sudo().env['res.users.identitycheck'].create({
            'request': json.dumps([
                { # strip non-jsonable keys (e.g. mapped to recordsets)
                    k: v for k, v in self.env.context.items()
                    if _jsonable(v)
                },
                self._name,
                self.ids,
                fn.__name__,
                args,
                kwargs
            ])
        })
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'res.users.identitycheck',
            'res_id': w.id,
            'name': _("Access Control"),
            'target': 'new',
            'views': [(False, 'form')],
            'context': {'dialog_size': 'medium'},
        }
    wrapped.__has_check_identity = True
    return wrapped
