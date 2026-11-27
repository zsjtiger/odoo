# Part of Odoo. See LICENSE file for full copyright and licensing details.

import logging

from docutils import nodes
from docutils.transforms import Transform, writer_aux
from docutils.writers.html4css1 import Writer



_logger = logging.getLogger('odoo.addons.base.models.ir_module')


class MyFilterMessages(Transform):
    """
    Custom docutils transform to remove `system message` for a document and
    generate warnings.

    (The standard filter removes them based on some `report_level` passed in
    the `settings_override` dictionary, but if we use it, we can't see them
    and generate warnings.)
    """
    default_priority = 870

    def apply(self):
        # Use `findall()` if available (docutils >= 0.20), otherwise fallback to `traverse()`.
        # This ensures compatibility across environments with different docutils versions.
        if hasattr(self.document, 'findall'):
            nodes_iter = self.document.findall(nodes.system_message)
        else:
            nodes_iter = self.document.traverse(nodes.system_message)

        for node in nodes_iter:
            _logger.debug("docutils' system message present: %s", str(node))
            node.parent.remove(node)


class MyWriter(Writer):
    """
    Custom docutils html4ccs1 writer that doesn't add the warnings to the
    output document.
    """
    def get_transforms(self):
        return [MyFilterMessages, writer_aux.Admonitions]
