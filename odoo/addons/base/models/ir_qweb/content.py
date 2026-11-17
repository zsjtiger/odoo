"""The contents of the QWeb engine: the lazy snippets and the JSON values."""

from __future__ import annotations

import typing

import threading
from markupsafe import Markup
from collections.abc import Mapping
from odoo.tools import BinaryValue, json

if typing.TYPE_CHECKING:
    from .model import IrQweb
    from .stack import QwebCallParameters


class QwebContent:
    """ QwebContent wraps a snippet to be used as a string value or a fragment.
        If the value is used with a string operation (from a qweb directive
        like `t-att-help="value % 1"`), the QwebContent loads the snippet.
        If the value is inserted in the document (`t-out="value"`), the snippet
        params bubble up to `_render_iterall`.
    """
    irQweb: IrQweb
    html: str | None
    params__: QwebCallParameters  # not available for the python expression inside the xml

    def __init__(self, irQweb: IrQweb, params: QwebCallParameters, process):
        self.__irQweb = irQweb
        self.html = None
        self.params__ = params
        self.process__ = process

    @property
    def irQweb(self):
        irQweb = self.__irQweb
        thread_dbname = getattr(threading.current_thread(), 'dbname', None)
        if thread_dbname and thread_dbname != irQweb.env.cr.dbname:
            return None
        return irQweb

    def __str__(self):
        if self.html is None:
            if self.irQweb is None:
                return ''
            params = self.params__
            process = self.process__
            self.html = ''.join(self.irQweb._render_iterall(
               params.view_ref, params.method, params.values, params.root_values, process, params.directive,
            ))
        return self.html

    def __repr__(self):
        return f'<QwebContent {self.params__!r}>'

    def __len__(self):
        return len(str(self))

    def __html__(self):
        return self.__str__()

    def __contains__(self, key):
        return key in Markup(self)

    def __getattr__(self, name):
        return getattr(Markup(self), name)

    def __getitem__(self, key):
        return Markup(self)[key]

    def __add__(self, other):
        return Markup(self).__add__(other)

    def __radd__(self, other):
        return Markup(self).__radd__(other)

    def __mod__(self, other):
        return Markup(self).__mod__(other)

    def __rmod__(self, other):
        return Markup(self).__rmod__(other)


class QwebJSON(json.JSON):

    def default(self, obj):
        if isinstance(obj, Mapping):
            return dict(obj)
        if isinstance(obj, BinaryValue):
            return obj.decode()
        return obj

    def dumps(self, *args, **kwargs):
        prev_default = kwargs.pop('default', self.default)
        return super().dumps(*args, **kwargs, default=(
            lambda obj: prev_default(str(obj) if isinstance(obj, QwebContent) else obj)
        ))


qwebJSON = QwebJSON()
