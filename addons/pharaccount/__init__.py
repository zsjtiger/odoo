# -*- coding: utf-8 -*-
from . import models


def _post_init_hook(env):
    """On install: create the pharmacy record types and enable record types on accounts."""
    env['ir.record.type']._pharaccount_create_default_types()
    env['ir.model']._get('pharaccount.account').action_enable_record_type()
