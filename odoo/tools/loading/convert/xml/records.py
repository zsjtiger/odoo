"""The records of the XML data files: the records, their deletion and their functions."""

from odoo.tools.config import config
from odoo.tools.safe_eval import safe_eval
from ..common import _get_eval_context, nodeattr2bool, str2bool

from .base import _logger
from .values import _eval_xml

def _tag_delete(self, rec):
    d_model = rec.get("model")
    records = self.env[d_model]

    if d_search := rec.get("search"):
        context = _get_eval_context(self, self.env, d_model)
        try:
            records = records.search(safe_eval(d_search, context))
        except ValueError:
            _logger.warning('Skipping deletion for failed search `%r`', d_search, exc_info=True)

    if d_id := rec.get("id"):
        try:
            records += records.browse(self.id_get(d_id))
        except ValueError:
            # d_id cannot be found. doesn't matter in this case
            _logger.warning('Skipping deletion for missing XML ID `%r`', d_id, exc_info=True)

    if records:
        records.unlink()


def _tag_function(self, rec):
    if self.noupdate and self.mode != 'init':
        return
    env = self.get_env(rec)
    _eval_xml(self, rec, env)


def _tag_record(self, rec, extra_vals=None):
    rec_model = rec.get("model")
    env = self.get_env(rec)
    rec_id = rec.get("id", '')

    model = env[rec_model]

    if self.xml_filename and rec_id:
        model = model.with_context(
            install_mode=True,
            install_module=self.module,
            install_filename=self.xml_filename,
        )

    self._test_xml_id(rec_id)
    xid = self.make_xml_id(rec_id)

    # in update mode, the record won't be updated if the data node explicitly
    # opt-out using @noupdate="1". A second check will be performed in
    # model._load_records() using the record's ir.model.data `noupdate` field.
    if self.noupdate and self.mode != 'init':
        # check if the xml record has no id, skip
        if not rec_id:
            return None

        if record := env['ir.model.data']._load_xmlid(xid):
            for child in rec.xpath('.//record[@id]'):
                sub_xid = child.get("id")
                self._test_xml_id(sub_xid)
                sub_xid = self.make_xml_id(sub_xid)
                if sub_record := env['ir.model.data']._load_xmlid(sub_xid):
                    self.idref[sub_xid] = sub_record.id

            # if the resource already exists, don't update it but store
            # its database id (can be useful)
            self.idref[xid] = record.id
            return None
        elif not nodeattr2bool(rec, 'forcecreate', True):
            # if it doesn't exist and we shouldn't create it, skip it
            return None
        # else create it normally

    foreign_record_to_create = False
    if xid and xid.partition('.')[0] != self.module:
        # updating a record created by another module
        record = self.env['ir.model.data']._load_xmlid(xid)
        if not record and not (foreign_record_to_create := nodeattr2bool(rec, 'forcecreate')):  # Allow foreign records if explicitely stated
            if self.noupdate and not nodeattr2bool(rec, 'forcecreate', True):
                # if it doesn't exist and we shouldn't create it, skip it
                return None
            raise Exception("Cannot update missing record %r" % xid)

    from odoo.fields import Command  # noqa: PLC0415
    res = {}
    sub_records = []
    for field in rec.iterchildren('field'):
        #TODO: most of this code is duplicated above (in _eval_xml)...
        f_name = field.get("name")
        if '@' in f_name:
            continue  # used for translations
        f_model = field.get("model")
        if not f_model and f_name in model._fields and model._fields[f_name].relational:
            f_model = model._fields[f_name].comodel_name
        f_use = field.get("use",'') or 'id'
        f_val = False

        if f_search := field.get("search"):
            assert f_model, 'Define an attribute model="..." in your .XML file!'
            context = _get_eval_context(self, env, f_model)
            q = safe_eval(f_search, context)
            # browse the objects searched
            s = env[f_model].search(q)
            # column definitions of the "local" object
            _fields = env[rec_model]._fields
            # if the current field is many2many
            if (f_name in _fields) and _fields[f_name].type == 'many2many':
                f_val = [Command.set([x[f_use] for x in s])]
            elif len(s):
                # otherwise (we are probably in a many2one field),
                # take the first element of the search
                f_val = s[0][f_use]
        elif f_ref := field.get("ref"):
            if f_name in model._fields and model._fields[f_name].type == 'reference':
                val = self.model_id_get(f_ref)
                f_val = val[0] + ',' + str(val[1])
            else:
                f_val = self.id_get(f_ref, raise_if_not_found=nodeattr2bool(rec, 'forcecreate', True))
                if not f_val:
                    _logger.warning("Skipping creation of %r because %s=%r could not be resolved", xid, f_name, f_ref)
                    return None
        else:
            f_val = _eval_xml(self, field, env)
            if f_name in model._fields:
                field_type = model._fields[f_name].type
                if field_type == 'many2one':
                    f_val = int(f_val) if f_val else False
                elif field_type == 'integer':
                    f_val = int(f_val)
                elif field_type in ('float', 'monetary'):
                    f_val = float(f_val)
                elif field_type == 'boolean' and isinstance(f_val, str):
                    f_val = str2bool(f_val)
                elif field_type == 'one2many':
                    for child in field.iterchildren('record'):
                        sub_records.append((child, model._fields[f_name].inverse_name))
                    if isinstance(f_val, str):
                        # We do not want to write on the field since we will write
                        # on the childrens' parents later
                        continue
                elif field_type == 'html':
                    if field.get('type') == 'xml':
                        _logger.warning('HTML field %r is declared as `type="xml"`', f_name)
        res[f_name] = f_val
    if extra_vals:
        res.update(extra_vals)
    if 'sequence' not in res and 'sequence' in model._fields:
        sequence = self.next_sequence()
        if sequence:
            res['sequence'] = sequence
    if 'xmlid' not in res and 'xmlid' in model._fields:
        res['xmlid'] = xid

    data = dict(xml_id=xid, values=res, noupdate=self.noupdate)
    if foreign_record_to_create:
        model = model.with_context(foreign_record_to_create=foreign_record_to_create)
    record = model._load_records([data], self.mode == 'update')
    if xid:
        self.idref[xid] = record.id
    if config.get('import_partial'):
        env.cr.commit()
    for child_rec, inverse_name in sub_records:
        self._tag_record(child_rec, extra_vals={inverse_name: record.id})
    return rec_model, record.id
