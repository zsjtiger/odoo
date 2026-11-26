# -*- coding: utf-8 -*-
from . import models


def _post_init_hook(env):
    """On install, mirror the record types from the data file into ir.record.type."""
    env['pharaccount.record.type']._sync_to_record_types()
