"""Common helpers of the data files: the modes of the import, the references and the evaluation contexts."""

import typing
import zoneinfo
from datetime import datetime, timedelta, UTC, tzinfo
from dateutil.relativedelta import relativedelta
from odoo.tools.safe_eval import time




ConvertMode = typing.Literal['init', 'update']


IdRef = dict[str, int | typing.Literal[False]]


class Pytz(typing.NamedTuple):
    timezone: typing.Callable[[str], zoneinfo.ZoneInfo]
    utc: tzinfo
    UTC: tzinfo


class ParseError(Exception):
    ...


def _get_eval_context(self, env, model_str):
    from odoo import fields, release  # noqa: PLC0415
    context = dict(Command=fields.Command,
                  time=time,
                  DateTime=datetime,
                  datetime=datetime,
                  timedelta=timedelta,
                  relativedelta=relativedelta,
                  version=release.major_version,
                  ref=self.id_get,
                  pytz=Pytz(zoneinfo.ZoneInfo, UTC, UTC))
    if model_str:
        context['obj'] = env[model_str].browse
    return context


def str2bool(value):
    return value.lower() not in ('0', 'false', 'off')


def nodeattr2bool(node, attr, default=False):
    if not node.get(attr):
        return default
    val = node.get(attr).strip()
    if not val:
        return default
    return str2bool(val)
