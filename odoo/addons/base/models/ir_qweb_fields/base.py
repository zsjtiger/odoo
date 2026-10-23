"""The base field of the QWeb engine: the conversion of a field value to HTML, shared by the other fields."""

from __future__ import annotations

from markupsafe import escape
from odoo import api, models
from odoo.tools import BinaryValue
from odoo.tools.misc import get_lang


class IrQwebField(models.AbstractModel):
    """ Used to convert a t-field specification into an output HTML field.

    :meth:`~.to_html` is the entry point of this conversion from QWeb, it:

    * converts the record value to html using :meth:`~.record_to_html`
    * generates the metadata attributes (``data-oe-``) to set on the root
      result node
    * generates the root result node itself through :meth:`~.render_element`
    """
    _name = 'ir.qweb.field'
    _description = 'Qweb Field'

    @api.model
    def get_available_options(self):
        """ Get the available option informations.

        :rtype: dict[str, dict[str, Any]]
        :return: A dictionnary that maps option names' to their settings.

            The settings are dict themselves and have the following keys:

            type

                Guaranteed, one of ``'string'``, ``'integer'``, ``'float'``,
                ``'model'``, ``'array'``, or ``'selection'``.

            string

                Guaranteed

            description

                Optional

            required

                Optional, is assumed ``False`` when absent, otherwise
                is either ``True`` or a string.

            params

                Optional

            default_value

                Optional, the default value, as a json-friendly type.

            Example::

                {
                    <option>: {
                        # guaranteed
                        'type': ...,
                        'string': ...,
                        # optional
                        'default_value': ...,
                        'description': ...,
                        'params': ...,
                        'required': ...,
                    }
                }
        """
        return {}

    @api.model
    def attributes(self, record, field_name, options, values=None):
        """ attributes(record, field_name, field, options, values)

        Generates the metadata attributes (prefixed by ``data-oe-``) for the
        root node of the field conversion.

        The default attributes are:

        * ``model``, the name of the record's model
        * ``id`` the id of the record to which the field belongs
        * ``type`` the logical field type (widget, may not match the field's
          ``type``, may not be any Field subclass name)
        * ``translate``, a boolean flag (``0`` or ``1``) denoting whether the
          field is translatable
        * ``readonly``, has this attribute if the field is readonly
        * ``expression``, the original expression

        :returns: dict (attribute name, attribute value).
        """
        data = {}
        field = record._fields[field_name]

        if not options['inherit_branding'] and not options['translate']:
            return data

        data['data-oe-model'] = record._name
        data['data-oe-id'] = record.id
        data['data-oe-field'] = field.name
        data['data-oe-type'] = options.get('type')
        data['data-oe-expression'] = options.get('expression')
        if field.readonly:
            data['data-oe-readonly'] = 1
        return data

    @api.model
    def value_to_html(self, value, options):
        """ value_to_html(value, field, options=None)

        Converts a single value to its HTML version/output
        :rtype: unicode
        """
        if value is None or value is False:
            return ''
        if isinstance(value, (bytes, BinaryValue)):
            value = value.decode()

        return escape(value)

    @api.model
    def record_to_html(self, record, field_name, options):
        """ record_to_html(record, field_name, options)

        Converts the specified field of the ``record`` to HTML

        :rtype: unicode
        """
        if not record:
            return False
        value = record.with_context(**self.env.context)[field_name]
        return False if value is False else self.value_to_html(value, options=options)

    @api.model
    def user_lang(self):
        """ user_lang()

        Fetches the res.lang record corresponding to the language code stored
        in the user's context.

        :returns: Model[res.lang]
        """
        return self.env['res.lang'].browse(get_lang(self.env).id)
