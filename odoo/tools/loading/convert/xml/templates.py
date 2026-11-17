"""The menus, the templates and the assets of the XML data files, and the records they create."""

from lxml import etree, builder
from ..common import nodeattr2bool


def _tag_menuitem(self, rec, parent=None):
    rec_id = rec.attrib["id"]
    self._test_xml_id(rec_id)

    # The parent attribute was specified, if non-empty determine its ID, otherwise
    # explicitly make a top-level menu
    values = {
        'parent_id': False,
        'active': nodeattr2bool(rec, 'active', default=True),
    }

    if rec.get('sequence'):
        values['sequence'] = int(rec.get('sequence'))

    if parent is not None:
        values['parent_id'] = parent
    elif rec.get('parent'):
        values['parent_id'] = self.id_get(rec.attrib['parent'])
    elif rec.get('web_icon'):
        values['web_icon'] = rec.attrib['web_icon']


    if rec.get('name'):
        values['name'] = rec.attrib['name']

    if rec.get('action'):
        a_action = rec.attrib['action']

        if '.' not in a_action:
            a_action = '%s.%s' % (self.module, a_action)
        act = self.env.ref(a_action).sudo()
        values['action'] = "%s,%d" % (act.type, act.id)

        if not values.get('name') and act.type.endswith(('act_window', 'wizard', 'url', 'client', 'server')) and act.name:
            values['name'] = act.name

    if not values.get('name'):
        values['name'] = rec_id or '?'

    from odoo.fields import Command  # noqa: PLC0415
    groups = []
    for group in rec.get('groups', '').split(','):
        if group.startswith('-'):
            group_id = self.id_get(group[1:])
            groups.append(Command.unlink(group_id))
        elif group:
            group_id = self.id_get(group)
            groups.append(Command.link(group_id))
    if groups:
        values['group_ids'] = groups


    data = {
        'xml_id': self.make_xml_id(rec_id),
        'values': values,
        'noupdate': self.noupdate,
    }
    menu = self.env['ir.ui.menu']._load_records([data], self.mode == 'update')
    for child in rec.iterchildren('menuitem'):
        self._tag_menuitem(child, parent=menu.id)


def _tag_template(self, el):
    # This helper transforms a <template> element into a <record> and forwards it
    tpl_id = el.get('id', el.get('t-name'))
    full_tpl_id = tpl_id
    attrib = el.attrib
    if '.' not in full_tpl_id:
        full_tpl_id = '%s.%s' % (self.module, tpl_id)
    # set the full template name for qweb <module>.<id>
    if not el.get('inherit_id'):
        el.set('t-name', full_tpl_id)
        el.tag = 't'
    else:
        el.tag = 'data'
    attrib.pop('id', None)

    if self.module.startswith('theme_'):
        model = 'theme.ir.ui.view'
    else:
        model = 'ir.ui.view'

    record_attrs = {
        'id': tpl_id,
        'model': model,
    }
    for att in ['forcecreate', 'context']:
        if att in attrib:
            record_attrs[att] = attrib.pop(att)

    Field = builder.E.field
    name = el.get('name', tpl_id)

    record = etree.Element('record', attrib=record_attrs)
    record.append(Field(name, name='name'))
    record.append(Field(full_tpl_id, name='key'))
    record.append(Field("qweb", name='type'))
    if 'track' in attrib:
        record.append(Field(attrib.pop('track'), name='track'))
    if 'priority' in attrib:
        record.append(Field(attrib.pop('priority'), name='priority'))
    if 'inherit_id' in attrib:
        record.append(Field(name='inherit_id', ref=attrib.pop('inherit_id')))
    if 'technical_usage' in attrib:
        record.append(Field(attrib.pop('technical_usage'), name='technical_usage'))
    if 'website_id' in attrib:
        record.append(Field(name='website_id', ref=attrib.pop('website_id')))
    if 'key' in attrib:
        record.append(Field(attrib.pop('key'), name='key'))

    # If the "active" value is set on the root node (instead of an inner
    # <field>), it is treated as the value for the "active" field but only
    # when *not updating*. This allows to update the record in a more recent
    # version without changing its active state (compatibility).
    if (active := attrib.pop('active', None)) in ("True", "False"):
        view_id = self.id_get(tpl_id, raise_if_not_found=False)
        if self.mode != "update" or not view_id:
            record.append(Field(name='active', eval=active))

    if (customize_show := attrib.pop('customize_show', None)) in ("True", "False"):
        record.append(Field(name='customize_show', eval=customize_show))
    groups = attrib.pop('groups', None)
    if groups:
        grp_lst = [("ref('%s')" % x) for x in groups.split(',')]
        record.append(Field(name="group_ids", eval="[Command.set(["+', '.join(grp_lst)+"])]"))
    if attrib.pop('primary', None) == 'True':
        # Pseudo clone mode, we'll set the t-name to the full canonical xmlid
        el.append(
            builder.E.xpath(
                builder.E.attribute(full_tpl_id, name='t-name'),
                expr=".",
                position="attributes",
            )
        )
        record.append(Field('primary', name='mode'))
    # inject complete <template> element (after changing node name) into
    # the ``arch`` field
    record.append(Field(el, name="arch", type="xml"))

    return self._tag_record(record)


def _tag_asset(self, el):
    """
    Transforms an <asset> element into a <record> and forwards it.
    """
    asset_id = el.get('id')
    Field = builder.E.field

    record = etree.Element('record', attrib={
        'id': asset_id,
        'model': 'theme.ir.asset' if self.module.startswith('theme_') else 'ir.asset',
    })

    name = el.get('name', asset_id)
    record.append(Field(name, name='name'))

    # E.g. <bundle directive="prepend">web.assets_frontend</bundle>
    # (directive is optional)
    bundle_el = el.find('bundle')
    record.append(Field(bundle_el.text, name='bundle'))
    if 'directive' in bundle_el.attrib:
        record.append(Field(bundle_el.get('directive'), name='directive'))

    # E.g. <path>website/static/src/snippets/s_share/000.scss</path>
    record.append(Field(el.find('path').text, name='path'))

    # Same as <template> for ir.ui.view:
    # If the "active" value is set on the root node (instead of an inner
    # <field>), it is treated as the value for the "active" field but only
    # when *not updating*. This allows to update the record in a more recent
    # version without changing its active state (compatibility).
    if el.get('active') in ("True", "False"):
        record_id = self.id_get(asset_id, raise_if_not_found=False)
        if self.mode != "update" or not record_id:
            record.append(Field(name='active', eval=el.get('active')))

    for child in el.iterchildren('field'):
        record.append(child)

    return self._tag_record(record)
