"""Translation files: the readers and the writers of the PO, CSV, XML and tar files."""

from __future__ import annotations

import codecs
import io
import logging
import os
import polib
import re
import tarfile
import typing
from collections import defaultdict
from datetime import datetime
from os.path import join
from pathlib import Path
from lxml import etree
from odoo.tools.misc import OrderedSet
import csv # pylint: disable=deprecated-module

if typing.TYPE_CHECKING:

    pass

from .base import parse_xmlid
from .lazy import _

_logger = logging.getLogger('odoo.tools.text.translate')


def translation_file_reader(source, fileformat='po', module=None):
    """ Iterate over translation file to return Odoo translation entries """
    if fileformat == 'csv':
        if module is not None:
            # if `module` is provided, we are reading a data file located in that module
            return CSVDataFileReader(source, module)
        return CSVFileReader(source)
    if fileformat == 'po':
        return PoFileReader(source)
    if fileformat == 'xml':
        assert module
        return XMLDataFileReader(source, module)
    _logger.info('Bad file format: %s', fileformat)
    raise Exception(_('Bad file format: %s', fileformat))


class CSVFileReader:
    def __init__(self, source):
        _reader = codecs.getreader('utf-8')
        self.source = csv.DictReader(_reader(source), quotechar='"', delimiter=',')
        self.prev_code_src = ""

    def __iter__(self):
        for entry in self.source:

            # determine <module>.<imd_name> from res_id
            if entry["res_id"] and entry["res_id"].isnumeric():
                # res_id is an id or line number
                entry["res_id"] = int(entry["res_id"])
            elif not entry.get("imd_name"):
                # res_id is an external id and must follow <module>.<name>
                entry["module"], entry["imd_name"] = entry["res_id"].split(".")
                entry["res_id"] = None
            if entry["type"] == "model" or entry["type"] == "model_terms":
                entry["imd_model"] = entry["name"].partition(',')[0]

            if entry["type"] == "code":
                if entry["src"] == self.prev_code_src:
                    # skip entry due to unicity constrain on code translations
                    continue
                self.prev_code_src = entry["src"]

            yield entry


class CSVDataFileReader:
    def __init__(self, source, module: str):
        """Read the translations in CSV data file.

        :param source: the input stream
        :param module: the CSV file is considered as a data file possibly
                       containing terms translated with the `@` syntax
        """
        _reader = codecs.getreader('utf-8')
        self.module = module
        self.model = os.path.splitext((os.path.basename(source.name)))[0].split('-')[0]
        self.source = csv.DictReader(_reader(source), quotechar='"', delimiter=',')
        self.prev_code_src = ""

    def __iter__(self):
        translated_fnames = sorted(
            [fname.split('@', maxsplit=1) for fname in self.source.fieldnames or [] if '@' in fname],
            key=lambda x: x[1],  # Put fallback languages first
        )
        for entry in self.source:
            for fname, lang in translated_fnames:
                module, imd_name = parse_xmlid(entry['id'], self.module)
                yield {
                    'type': 'model',
                    'imd_model': self.model,
                    'imd_name': imd_name,
                    'lang': lang,
                    'value': entry[f"{fname}@{lang}"],
                    'src': entry[fname],
                    'module': module,
                    'name': f"{self.model},{fname}",
                }


class XMLDataFileReader:
    def __init__(self, source, module: str):
        try:
            tree = etree.parse(source)
        except etree.LxmlSyntaxError:
            _logger.warning("Error parsing XML file %s", source)
            tree = etree.fromstring('<data/>')
        self.source = tree
        self.module = module

    def __iter__(self):
        for record in self.source.xpath("//field[contains(@name, '@')]/.."):
            vals = {field.attrib['name']: field.text for field in record.xpath("field")}
            translated_fnames = sorted(
                [fname.split('@', maxsplit=1) for fname in vals if '@' in fname],
                key=lambda x: x[1],  # Put fallback languages first
            )
            for fname, lang in translated_fnames:
                module, imd_name = parse_xmlid(record.attrib['id'], self.module)
                yield {
                    'type': 'model',
                    'imd_model': record.attrib['model'],
                    'imd_name': imd_name,
                    'lang': lang,
                    'value': vals[f"{fname}@{lang}"],
                    'src': vals[fname],
                    'module': module,
                    'name': f"{record.attrib['model']},{fname}",
                }


class PoFileReader:
    """ Iterate over po file to return Odoo translation entries """
    def __init__(self, source):

        def get_pot_path(source_name):
            # when fileobj is a TemporaryFile, its name is an inter in P3, a string in P2
            if isinstance(source_name, str) and source_name.endswith('.po'):
                # Normally the path looks like /path/to/xxx/i18n/lang.po
                # and we try to find the corresponding
                # /path/to/xxx/i18n/xxx.pot file.
                # (Sometimes we have 'i18n_extra' instead of just 'i18n')
                path = Path(source_name)
                filename = path.parent.parent.name + '.pot'
                pot_path = path.with_name(filename)
                return pot_path.exists() and str(pot_path) or False
            return False

        # polib accepts a path or the file content as a string, not a fileobj
        if isinstance(source, str):
            self.pofile = polib.pofile(source)
            pot_path = get_pot_path(source)
        else:
            # either a BufferedIOBase or result from NamedTemporaryFile
            self.pofile = polib.pofile(source.read().decode())
            pot_path = get_pot_path(source.name)

        if pot_path:
            # Make a reader for the POT file
            # (Because the POT comments are correct on GitHub but the
            # PO comments tends to be outdated. See LP bug 933496.)
            self.pofile.merge(polib.pofile(pot_path))

    def __iter__(self):
        for entry in self.pofile:
            if entry.obsolete:
                continue

            # in case of moduleS keep only the first
            match = re.match(r"(module[s]?): (\w+)", entry.comment)
            _, module = match.groups()
            comments = "\n".join([c for c in entry.comment.split('\n') if not c.startswith('module:')])
            source = entry.msgid
            translation = entry.msgstr
            found_code_occurrence = False
            for occurrence, line_number in entry.occurrences:
                match = re.match(r'(model|model_terms):([\w.]+),([\w]+):(\w+)\.([^ ]+)', occurrence)
                if match:
                    type, model_name, field_name, module, xmlid = match.groups()
                    yield {
                        'type': type,
                        'imd_model': model_name,
                        'name': model_name+','+field_name,
                        'imd_name': xmlid,
                        'res_id': None,
                        'src': source,
                        'value': translation,
                        'comments': comments,
                        'module': module,
                    }
                    continue

                match = re.match(r'(code):([\w/.]+)', occurrence)
                if match:
                    type, name = match.groups()
                    if found_code_occurrence:
                        # unicity constrain on code translation
                        continue
                    found_code_occurrence = True
                    yield {
                        'type': type,
                        'name': name,
                        'src': source,
                        'value': translation,
                        'comments': comments,
                        'res_id': int(line_number),
                        'module': module,
                    }
                    continue

                match = re.match(r'(selection):([\w.]+),([\w]+)', occurrence)
                if match:
                    _logger.info("Skipped deprecated occurrence %s", occurrence)
                    continue

                match = re.match(r'(sql_constraint|constraint):([\w.]+)', occurrence)
                if match:
                    _logger.info("Skipped deprecated occurrence %s", occurrence)
                    continue
                _logger.error("malformed po file: unknown occurrence: %s", occurrence)


def TranslationFileWriter(target, fileformat='po', lang=None):
    """ Iterate over translation file to return Odoo translation entries """
    if fileformat == 'csv':
        return CSVFileWriter(target)

    if fileformat == 'po':
        return PoFileWriter(target, lang=lang)

    if fileformat == 'tgz':
        return TarFileWriter(target, lang=lang)

    raise Exception(_('Unrecognized extension: must be one of '
                      '.csv, .po, or .tgz (received .%s).') % fileformat)


_writer = codecs.getwriter('utf-8')


class CSVFileWriter:
    def __init__(self, target):
        self.writer = csv.writer(_writer(target), dialect='UNIX')
        # write header first
        self.writer.writerow(("module","type","name","res_id","src","value","comments"))


    def write_rows(self, rows):
        for module, type, name, res_id, src, trad, comments in rows:
            comments = '\n'.join(comments)
            self.writer.writerow((module, type, name, res_id, src, trad, comments))


class PoFileWriter:
    """ Iterate over po file to return Odoo translation entries """
    def __init__(self, target, lang):

        self.buffer = target
        self.lang = lang
        self.po = polib.POFile()

    def write_rows(self, rows):
        # we now group the translations by source. That means one translation per source.
        grouped_rows = {}
        modules = set()
        for module, type, name, res_id, src, trad, comments in rows:
            row = grouped_rows.setdefault(src, {})
            row.setdefault('modules', set()).add(module)
            if not row.get('translation') and trad != src:
                row['translation'] = trad
            row.setdefault('tnrs', []).append((type, name, res_id))
            row.setdefault('comments', set()).update(comments)
            modules.add(module)

        for src, row in sorted(grouped_rows.items()):
            if not self.lang:
                # translation template, so no translation value
                row['translation'] = ''
            elif not row.get('translation'):
                row['translation'] = ''
            self.add_entry(sorted(row['modules']), sorted(row['tnrs']), src, row['translation'], sorted(row['comments']))

        import odoo.release as release
        self.po.header = "Translation of %s.\n" \
                    "This file contains the translation of the following modules:\n" \
                    "%s" % (release.description, ''.join("\t* %s\n" % m for m in modules))
        now = datetime.utcnow().strftime('%Y-%m-%d %H:%M+0000')
        self.po.metadata = {
            'Project-Id-Version': "%s %s" % (release.description, release.version),
            'Report-Msgid-Bugs-To': '',
            'POT-Creation-Date': now,
            'PO-Revision-Date': now,
            'Last-Translator': '',
            'Language-Team': '',
            'MIME-Version': '1.0',
            'Content-Type': 'text/plain; charset=UTF-8',
            'Content-Transfer-Encoding': '',
            'Plural-Forms': '',
        }

        # buffer expects bytes
        self.buffer.write(str(self.po).encode())

    def add_entry(self, modules, tnrs, source, trad, comments=None):
        entry = polib.POEntry(
            msgid=source,
            msgstr=trad,
        )
        plural = len(modules) > 1 and 's' or ''
        entry.comment = "module%s: %s" % (plural, ', '.join(modules))
        if comments:
            entry.comment += "\n" + "\n".join(comments)
        occurrences = OrderedSet()
        for type_, *ref in tnrs:
            if type_ == "code":
                fpath, lineno = ref
                name = f"code:{fpath}"
                # lineno is set to 0 to avoid creating diff in PO files every
                # time the code is moved around
                lineno = "0"
            else:
                field_name, xmlid = ref
                name = f"{type_}:{field_name}:{xmlid}"
                lineno = None   # no lineno for model/model_terms sources
            occurrences.add((name, lineno))
        entry.occurrences = list(occurrences)
        self.po.append(entry)


class TarFileWriter:

    def __init__(self, target, lang):
        self.tar = tarfile.open(fileobj=target, mode='w|gz')
        self.lang = lang

    def write_rows(self, rows):
        rows_by_module = defaultdict(list)
        for row in rows:
            module = row[0]
            rows_by_module[module].append(row)

        for mod, modrows in rows_by_module.items():
            with io.BytesIO() as buf:
                po = PoFileWriter(buf, lang=self.lang)
                po.write_rows(modrows)
                buf.seek(0)

                info = tarfile.TarInfo(
                    join(mod, 'i18n', '{basename}.{ext}'.format(
                        basename=self.lang or mod,
                        ext='po' if self.lang else 'pot',
                    )))
                # addfile will read <size> bytes from the buffer so
                # size *must* be set first
                info.size = len(buf.getvalue())

                self.tar.addfile(info, fileobj=buf)

        self.tar.close()
