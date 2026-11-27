"""The preprocessed stylesheets of the assets: Sass, SCSS and Less."""

from __future__ import annotations

import os
import re
import textwrap
from subprocess import Popen, PIPE
from odoo.tools import misc
from odoo.tools.profiling import profiler
from odoo.tools.misc import file_path

from .assets import StylesheetAsset
from .errors import CompileError

class PreprocessedCSS(StylesheetAsset):
    rx_import = None

    def get_command(self):
        raise NotImplementedError

    def compile(self, source):
        command = self.get_command()
        try:
            compiler = Popen(command, stdin=PIPE, stdout=PIPE,
                             stderr=PIPE, encoding='utf-8')
        except Exception:
            raise CompileError("Could not execute command %r" % command[0])

        out, err = compiler.communicate(input=source)
        if compiler.returncode:
            cmd_output = out + err
            if not cmd_output:
                cmd_output = u"Process exited with return code %d\n" % compiler.returncode
            raise CompileError(cmd_output)
        return out


class SassStylesheetAsset(PreprocessedCSS):
    rx_indent = re.compile(r'^( +|\t+)', re.M)
    indent = None
    reindent = '    '

    def minify(self):
        return self.with_header()

    def get_source(self):
        content = textwrap.dedent(self.inline or self._fetch_content())

        def fix_indent(m):
            # Indentation normalization
            ind = m.group()
            if self.indent is None:
                self.indent = ind
                if self.indent == self.reindent:
                    # Don't reindent the file if identation is the final one (reindent)
                    raise StopIteration()
            return ind.replace(self.indent, self.reindent)

        try:
            content = self.rx_indent.sub(fix_indent, content)
        except StopIteration:
            pass
        return "/*! %s */\n%s" % (self.id, content)

    def get_command(self):
        try:
            sass = misc.find_in_path('sass')
        except IOError:
            sass = 'sass'
        return [sass, '--stdin', '-t', 'compressed', '--unix-newlines', '--compass',
                '-r', 'bootstrap-sass']


class ScssStylesheetAsset(PreprocessedCSS):
    @property
    def bootstrap_path(self):
        return file_path('web/static/lib/bootstrap/scss')

    precision = 8
    output_style = 'expanded'

    def compile(self, source):
        try:
            import sass as libsass  # noqa: PLC0415
        except ModuleNotFoundError:
            return super().compile(source)

        def scss_importer(path, *args):
            *parent_path, file = os.path.split(path)
            try:
                parent_path = file_path(os.path.join(*parent_path))
            except FileNotFoundError:
                parent_path = file_path(os.path.join(self.bootstrap_path, *parent_path))
            return [(os.path.join(parent_path, file),)]

        try:
            profiler.force_hook()
            return libsass.compile(
                string=source,
                include_paths=[
                    self.bootstrap_path,
                ],
                importers=[(0, scss_importer)],
                output_style=self.output_style,
                precision=self.precision,
            )
        except libsass.CompileError as e:
            raise CompileError(e.args[0])

    def get_command(self):
        try:
            sassc = misc.find_in_path('sassc')
        except IOError:
            sassc = 'sassc'
        return [sassc, '--stdin', '--precision', str(self.precision), '--load-path', self.bootstrap_path, '-t', self.output_style]


class LessStylesheetAsset(PreprocessedCSS):
    def get_command(self):
        try:
            if os.name == 'nt':
                lessc = misc.find_in_path('lessc.cmd')
            else:
                lessc = misc.find_in_path('lessc')
        except IOError:
            lessc = 'lessc'
        return [lessc, '-', '--no-js', '--no-color']
