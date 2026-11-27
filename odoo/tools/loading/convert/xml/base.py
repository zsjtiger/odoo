"""The import of the XML data files: the parsing of the documents, the references of the records and the dispatch of the tags."""

import logging
import os.path
import pprint
import subprocess
from lxml import etree
from odoo.tools.config import config
from odoo.exceptions import ValidationError
from odoo.tools.safe_eval import safe_eval
from ..common import ConvertMode, IdRef, ParseError, nodeattr2bool


class xml_import(object):
    def get_env(self, node, eval_context=None):
        uid = node.get('uid')
        context = node.get('context')
        if uid or context:
            return self.env(
                user=uid and self.id_get(uid),
                context=context and {
                    **self.env.context,
                    **safe_eval(context, {
                        'ref': self.id_get,
                        **(eval_context or {})
                    }),
                }
            )
        return self.env
    def make_xml_id(self, xml_id):
        if not xml_id or '.' in xml_id:
            return xml_id
        return "%s.%s" % (self.module, xml_id)
    def _test_xml_id(self, xml_id):
        if '.' in xml_id:
            module, id = xml_id.split('.', 1)
            assert '.' not in id, """The ID reference "%s" must contain
maximum one dot. They are used to refer to other modules ID, in the
form: module.record_id""" % (xml_id,)
            if module != self.module:
                modcnt = self.env['ir.module.module'].search_count([('name', '=', module), ('state', '=', 'installed')])
                assert modcnt == 1, """The ID "%s" refers to an uninstalled module""" % (xml_id,)
    def _tag_delete(self, rec):
        return _records._tag_delete(self, rec)
    def _tag_function(self, rec):
        return _records._tag_function(self, rec)
    def _tag_menuitem(self, rec, parent=None):
        return _templates._tag_menuitem(self, rec, parent)
    def _tag_record(self, rec, extra_vals=None):
        return _records._tag_record(self, rec, extra_vals)
    def _tag_template(self, el):
        return _templates._tag_template(self, el)
    def _tag_asset(self, el):
        return _templates._tag_asset(self, el)
    def id_get(self, id_str, raise_if_not_found=True):
        id_str = self.make_xml_id(id_str)
        if id_str in self.idref:
            return self.idref[id_str]
        return self.model_id_get(id_str, raise_if_not_found)[1]
    def model_id_get(self, id_str, raise_if_not_found=True):
        id_str = self.make_xml_id(id_str)
        return self.env['ir.model.data']._xmlid_to_res_model_res_id(id_str, raise_if_not_found=raise_if_not_found)
    def _tag_root(self, el):
        for rec in el:
            f = self._tags.get(rec.tag)
            if f is None:
                continue

            self.envs.append(self.get_env(el))
            self._noupdate.append(nodeattr2bool(el, 'noupdate', self.noupdate))
            self._sequences.append(0 if nodeattr2bool(el, 'auto_sequence', False) else None)
            try:
                f(rec)
            except ParseError:
                raise
            except ValidationError as err:
                msg = "while parsing {file}:{viewline}\n{err}\n\nView error context:\n{context}\n".format(
                    file=rec.getroottree().docinfo.URL,
                    viewline=rec.sourceline,
                    context=pprint.pformat(getattr(err, 'context', None) or '-no context-'),
                    err=err.args[0],
                )
                _logger.debug(msg, exc_info=True)
                raise ParseError(msg) from None  # Restart with "--log-handler odoo.tools.loading.convert:DEBUG" for complete traceback
            except Exception as e:
                raise ParseError('while parsing %s:%s, somewhere inside\n%s' % (
                    rec.getroottree().docinfo.URL,
                    rec.sourceline,
                    etree.tostring(rec, encoding='unicode').rstrip()
                )) from e
            finally:
                self._noupdate.pop()
                self.envs.pop()
                self._sequences.pop()
    @property
    def env(self):
        return self.envs[-1]
    @property
    def noupdate(self):
        return self._noupdate[-1]
    def next_sequence(self):
        value = self._sequences[-1]
        if value is not None:
            value = self._sequences[-1] = value + 10
        return value
    def __init__(self, env, module, idref: IdRef | None, mode: ConvertMode, noupdate: bool = False, xml_filename: str = ''):
        self.mode = mode
        self.module = module
        self.envs = [env(context=dict(env.context, lang=None))]
        self.idref: IdRef = {} if idref is None else idref
        self._noupdate = [noupdate]
        self._sequences = []
        self.xml_filename = xml_filename
        self._tags = {
            'record': self._tag_record,
            'delete': self._tag_delete,
            'function': self._tag_function,
            'menuitem': self._tag_menuitem,
            'template': self._tag_template,
            'asset': self._tag_asset,

            **dict.fromkeys(self.DATA_ROOTS, self._tag_root)
        }
    def parse(self, de):
        assert de.tag in self.DATA_ROOTS, "Root xml tag must be <openerp>, <odoo> or <data>."
        self._tag_root(de)
    DATA_ROOTS = ['odoo', 'data', 'openerp']


_logger = logging.getLogger('odoo.tools.loading.convert')


try:
    import jingtrang
except ImportError:
    jingtrang = None


def convert_xml_import(
        env,
        module,
        xmlfile,
        idref: IdRef | None = None,
        mode: ConvertMode = 'init',
        noupdate=False,
        report=None,
):
    doc = etree.parse(xmlfile)
    schema = os.path.join(config.root_path, 'tools', 'import_xml.rng')
    relaxng = etree.RelaxNG(etree.parse(schema))
    try:
        relaxng.assert_(doc)
    except Exception:
        _logger.exception("The XML file '%s' does not fit the required schema!", xmlfile.name)
        if jingtrang:
            environ = os.environ.copy()
            environ['JAVA_TOOL_OPTIONS'] = '-Xmx64m -XX:-UseCompressedClassPointers'
            p = subprocess.run(
                ["pyjing", schema, xmlfile.name], stdout=subprocess.PIPE, env=environ,
            )
            _logger.warning(p.stdout.decode())
        else:
            for e in relaxng.error_log:
                _logger.warning(e)
            _logger.info("Install 'jingtrang' for more precise and useful validation messages.")
        raise

    if isinstance(xmlfile, str):
        xml_filename = xmlfile
    else:
        xml_filename = xmlfile.name
    obj = xml_import(env, module, idref, mode, noupdate=noupdate, xml_filename=xml_filename)
    obj.parse(doc.getroot())


# the delegated methods of the class, and the modules that use the class: at the end, they import this module
from . import records as _records, templates as _templates  # noqa: E402
