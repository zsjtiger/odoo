"""The character fields: the single-line and the multiline text fields."""

from __future__ import annotations

import typing
from operator import attrgetter
from odoo.tools import sql
from odoo.tools.text.translate import mark_as_copy

if typing.TYPE_CHECKING:
    pass

from .base import BaseString

class Char(BaseString):
    """ Basic string field, can be length-limited, usually displayed as a
    single-line string in clients.

    :param bool|callable copy: whether the field value should be copied when the
        record is duplicated; default like in base field definition except that
        a normal field named "name" will default to ``copy=mark_as_copy('name')``.

    :param int size: the maximum size of values stored for that field

    :param bool trim: states whether the value is trimmed or not (by default,
        ``True``). Note that the trim operation is applied by both the server code and the web client
        This ensures consistent behavior between imported data and UI-entered data.

        - The web client trims user input during in write/create flows in UI.
        - The server trims values during import (in `base_import`) to avoid discrepancies between
          trimmed form inputs and stored DB values.

    :param translate: enable the translation of the field's values; use
        ``translate=True`` to translate field values as a whole; ``translate``
        may also be a callable such that ``translate(callback, value)``
        translates ``value`` by using ``callback(term)`` to retrieve the
        translation of terms.
    :type translate: bool or callable
    """
    type = 'char'
    trim: bool = True                   # whether value is trimmed (only by web client and base_import)
    size: int | None = None             # maximum size of values

    def _setup_attrs__(self, model_class, name):
        super()._setup_attrs__(model_class, name)
        assert self.size is None or isinstance(self.size, int), \
            "Char field %s with non-integer size %r" % (self, self.size)

    def _get_attrs(self, model_class, name):
        attrs = super()._get_attrs(model_class, name)
        if self.name in ('name', 'x_name') and attrs.get('translate', False) in (True, False) and 'copy' not in attrs:
            # default name fields are copied with "(copy)" suffix
            attrs['copy'] = mark_as_copy(self.name)
        return attrs

    @property
    def _column_type(self):
        size = self.size
        assert size is None or type(size) is int, "size must be an integer"
        return ('varchar', f'varchar({size})' if size and size > 0 else 'varchar')

    def update_db_column(self, model, column):
        if (
            column and self.column_type[0] == 'varchar' and
            column['udt_name'] == 'varchar' and column['character_maximum_length'] and
            (self.size is None or column['character_maximum_length'] < self.size)
        ):
            # the column's varchar size does not match self.size; convert it
            sql.convert_column(model.env.cr, model._table, self.name, self.stored_sql_column_type)
        super().update_db_column(model, column)

    _related_size = property(attrgetter('size'))
    _related_trim = property(attrgetter('trim'))
    _description_size = property(attrgetter('size'))
    _description_trim = property(attrgetter('trim'))

    def get_depends(self, model):
        depends, depends_context = super().get_depends(model)

        # display_name may depend on context['lang'] (`test_lp1071710`)
        if (
            self.name == 'display_name'
            and self.compute
            and not self.store
            and model._rec_name
            and model._fields[model._rec_name].base_field.translate
            and 'lang' not in depends_context
        ):
            depends_context = [*depends_context, 'lang']

        return depends, depends_context


class Text(BaseString):
    """ Very similar to :class:`Char` but used for longer contents, usually
    displayed as a multiline text box.

    :param translate: enable the translation of the field's values; use
        ``translate=True`` to translate field values as a whole; ``translate``
        may also be a callable such that ``translate(callback, value)``
        translates ``value`` by using ``callback(term)`` to retrieve the
        translation of terms.
    :type translate: bool or callable
    """
    type = 'text'
    _column_type = ('text', 'text')
