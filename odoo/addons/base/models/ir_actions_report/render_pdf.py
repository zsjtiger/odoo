# Part of Odoo. See LICENSE file for full copyright and licensing details.
"""The rendering of the reports as PDF: the engines, the streams, the merges and the attachments."""

import io
import typing
from collections import OrderedDict
from collections.abc import Sequence
import requests
from PIL import Image
from odoo import _, modules, tools
from odoo.exceptions import AccessError, RedirectWarning, UserError, ValidationError
from odoo.tools.pdf import PdfFileReader, PdfFileWriter, PdfReadError
from odoo.tools.safe_eval import safe_eval, time

from .report import _logger

def retrieve_attachment(self, record):
    '''Retrieve an attachment for a specific record.

        :param record: The record owning of the attachment.
        :return: A recordset of length <=1 or None
        '''
    attachment_name = safe_eval(self.attachment, {'object': record, 'time': time}) if self.attachment else ''
    if not attachment_name:
        return None
    return record.env['ir.attachment'].search([
            ('name', '=', attachment_name),
            ('res_model', '=', self.model),
            ('res_id', '=', record.id)
    ], limit=1)


def get_pdf_engine_state(self, engine_name) -> typing.Literal['ok', 'upgrade', 'workers', 'broken', 'install']:
    """
        Returns the requested engine status.
        The state of the pdf engine: install, ok, upgrade, workers or broken.

        - ok: A binary was found with a recent version.
        - upgrade: The binary is an older version.
        - workers: Not enough workers found to perform the pdf rendering process (< 2 workers).
        - broken: A binary was found but not responding.
        - install: Starting state.

        :param engine_name: The engine to test
        """
    return 'install'


def _handle_merge_pdfs_error(self, error=None, error_stream=None):
    raise UserError(_("Odoo is unable to merge the generated PDFs."))


def _merge_pdfs(self, streams, handle_error=None):
    writer = PdfFileWriter()
    for stream in streams:
        try:
            reader = PdfFileReader(stream)
            writer.append_pages_from_reader(reader)
        except (PdfReadError, TypeError, NotImplementedError, ValueError) as e:
            if handle_error is None:
                self._handle_merge_pdfs_error(error=e, error_stream=stream)
            else:
                handle_error(error=e, error_stream=stream)
    result_stream = io.BytesIO()
    streams.append(result_stream)
    try:
        writer.write(result_stream)
    except PdfReadError:
        raise UserError(_("Odoo is unable to merge the generated PDFs."))
    return result_stream


def _render_qweb_pdf_prepare_streams(self, report_ref, data, res_ids=None):
    if not data:
        data = {}
    data.setdefault('report_type', 'pdf')

    # access the report details with sudo() but evaluation context as current user
    report_sudo = self._get_report(report_ref)
    has_duplicated_ids = res_ids and len(res_ids) != len(set(res_ids))

    collected_streams = OrderedDict()

    # Fetch the existing attachments from the database for later use.
    # Reload the stream from the attachment in case of 'attachment_use'.
    if res_ids:
        records = self.env[report_sudo.model].browse(res_ids)
        for record in records:
            res_id = record.id
            if res_id in collected_streams:
                continue

            stream = None
            attachment = None
            if not has_duplicated_ids and report_sudo.attachment and not self.env.context.get("report_pdf_no_attachment"):
                attachment = report_sudo.retrieve_attachment(record)

                # Extract the stream from the attachment.
                if attachment and report_sudo.attachment_use:
                    stream = io.BytesIO(attachment.raw)

                    # Ensure the stream can be saved in Image.
                    if attachment.mimetype.startswith('image'):
                        img = Image.open(stream)
                        new_stream = io.BytesIO()
                        img.convert("RGB").save(new_stream, format="pdf")
                        stream.close()
                        stream = new_stream

            collected_streams[res_id] = {
                'stream': stream,
                'attachment': attachment,
            }

    # Call the defined PDF engine to generate the missing streams.
    res_ids_wo_stream = [res_id for res_id, stream_data in collected_streams.items() if not stream_data['stream']]
    all_res_ids_wo_stream = res_ids if has_duplicated_ids else res_ids_wo_stream

    engine_name = self._get_pdf_engine(report_sudo)
    if engine_name == 'html':
        # PDF generation is not setup

        # Disable the debug mode in the PDF rendering in order to not split the
        # assets bundle into separated files to load. This is done because of
        # an issue in wkhtmltopdf failing to load the CSS/Javascript resources
        # in time.
        # Without this, the header/footer of the reports randomly disappear
        # because the resources files are not loaded in time.
        # https://github.com/wkhtmltopdf/wkhtmltopdf/issues/2083
        additional_context = {'debug': False}
        data.setdefault("debug", False)
        return self.with_context(**additional_context) \
            ._render_qweb_html(report_ref, all_res_ids_wo_stream, data=data)[0]

    is_pdf_engine_required = not res_ids or res_ids_wo_stream
    if is_pdf_engine_required:
        engine_state = self.get_pdf_engine_state(engine_name)
        if engine_state == 'install':
            # pdf engine is not installed
            # the call should be catched before (cf /report/get_pdf_engine_state) but
            # if get_pdf is called manually (email template), the check could be
            # bypassed
            raise UserError(_("Unable to find the pdf engine on this system. The PDF can not be created."))
        elif engine_state == 'broken':
            # pdf engine is installed but not working
            raise UserError(_("The pdf engine on this system is not working."))
        elif engine_state == 'workers':
            # the pdf engine is installed but not enough workers are available
            raise UserError(_("Not enough workers to generate the PDF. Please try another engine or upgrade your setup."))

        # Disable the debug mode in the PDF rendering in order to not split the assets bundle
        # into separated files to load. This is done because of an issue in wkhtmltopdf
        # failing to load the CSS/Javascript resources in time.
        # Without this, the header/footer of the reports randomly disappear
        # because the resources files are not loaded in time.
        # https://github.com/wkhtmltopdf/wkhtmltopdf/issues/2083
        additional_context = {'debug': False}
        data.setdefault("debug", False)

        html = self.with_context(**additional_context)._render_qweb_html(report_ref, all_res_ids_wo_stream, data=data)[0]

        pdf_content, html_ids = self._run_pdf_engine(engine_name, html, report_ref=report_ref, landscape=self.env.context.get('landscape'))

        if not has_duplicated_ids and report_sudo.attachment and set(res_ids_wo_stream) != set(html_ids):
            raise UserError(_(
                "Report template “%s” has an issue, please contact your administrator. \n\n"
                "Cannot separate file to save as attachment because the report's template does not contain the"
                " attributes 'data-oe-model' and 'data-oe-id' as part of the div with 'article' classname.",
                report_sudo.name,
            ))
        pdf_content_stream = io.BytesIO(pdf_content)
        # Printing a PDF report without any records. The content could be returned directly.
        if has_duplicated_ids or not res_ids:
            return {
                False: {
                    'stream': pdf_content_stream,
                    'attachment': None,
                }
            }

        # Split the pdf for each record using the PDF outlines.

        # Only one record: append the whole PDF.
        if len(res_ids_wo_stream) == 1:
            collected_streams[res_ids_wo_stream[0]]['stream'] = pdf_content_stream
            return collected_streams

        # In case of multiple docs, we need to split the pdf according the records.
        # In the simplest case of 1 res_id == 1 page, we use the PDFReader to print the
        # pages one by one.
        html_ids_wo_none = [x for x in html_ids if x]
        reader = PdfFileReader(pdf_content_stream)
        if len(reader.pages) == len(res_ids_wo_stream):
            for i, p in enumerate(reader.pages):
                attachment_writer = PdfFileWriter()
                attachment_writer.add_page(p)
                stream = io.BytesIO()
                attachment_writer.write(stream)
                collected_streams[res_ids_wo_stream[i]]['stream'] = stream
            return collected_streams

        # In cases where the number of res_ids != the number of pages,
        # we split the pdf based on top outlines computed by wkhtmltopdf.
        # An outline is a <h?> html tag found on the document. To retrieve this table,
        # we look on the pdf structure using pypdf to compute the outlines_pages from
        # the top level heading in /Outlines.
        if len(res_ids_wo_stream) > 1 and set(res_ids_wo_stream) == set(html_ids_wo_none):
            root = reader.trailer['/Root']
            has_valid_outlines = '/Outlines' in root and '/First' in root['/Outlines']
            if not has_valid_outlines:
                return {False: {
                    'report_action': self,
                    'stream': pdf_content_stream,
                    'attachment': None,
                }}

            outlines_pages = []
            node = root['/Outlines']['/First']
            while True:
                outlines_pages.append(root['/Dests'][node['/Dest']][0])
                if '/Next' not in node:
                    break
                node = node['/Next']
            outlines_pages = sorted(set(outlines_pages))

            # The number of outlines must be equal to the number of records to be able to split the document.
            has_same_number_of_outlines = len(outlines_pages) == len(res_ids_wo_stream)

            # There should be a top-level heading on first page
            has_top_level_heading = outlines_pages[0] == 0

            if has_same_number_of_outlines and has_top_level_heading:
                # Split the PDF according to outlines.
                for i, num in enumerate(outlines_pages):
                    to = outlines_pages[i + 1] if i + 1 < len(outlines_pages) else len(reader.pages)
                    attachment_writer = PdfFileWriter()
                    for p in reader.pages[num:to]:
                        attachment_writer.add_page(p)
                    stream = io.BytesIO()
                    attachment_writer.write(stream)
                    collected_streams[res_ids_wo_stream[i]]['stream'] = stream
            else:
                for res_id in res_ids_wo_stream:
                    individual_collected_stream = self._render_qweb_pdf_prepare_streams(report_ref=report_ref, data=data, res_ids=[res_id])
                    collected_streams[res_id]['stream'] = individual_collected_stream[res_id]['stream']
            return collected_streams
        collected_streams[False] = {'stream': pdf_content_stream, 'attachment': None}

    return collected_streams


def _prepare_pdf_report_attachment_vals_list(self, report, streams):
    """Hook to prepare attachment values needed for attachments creation
        during the pdf report generation.

        :param report: The report (with sudo) from a reference report_ref.
        :param streams: Dict of streams for each report containing the pdf content and existing attachments.
        :return: attachment values list needed for attachments creation.
        """
    attachment_vals_list = []
    for res_id, stream_data in streams.items():
        # An attachment already exists.
        if stream_data['attachment']:
            continue

        # if res_id is false
        # we are unable to fetch the record, it won't be saved as we can't split the documents unambiguously
        if not res_id or not stream_data['stream']:
            _logger.warning(
                "These documents were not saved as an attachment because the template of %s doesn't "
                "have any headers seperating different instances of it. If you want it saved,"
                "please print the documents separately", report.report_name)
            continue
        record = self.env[report.model].browse(res_id)
        attachment_name = safe_eval(report.attachment, {'object': record, 'time': time})

        # Unable to compute a name for the attachment.
        if not attachment_name:
            continue

        attachment_vals_list.append({
            'name': attachment_name,
            'raw': stream_data['stream'].getvalue(),
            'res_model': report.model,
            'res_id': record.id,
            'type': 'binary',
        })
    return attachment_vals_list


def _pre_render_qweb_pdf(self, report_ref, res_ids=None, data=None):
    if not data:
        data = {}
    if isinstance(res_ids, int):
        res_ids = [res_ids]
    data.setdefault('report_type', 'pdf')
    # In case of test environment without enough workers to perform calls to wkhtmltopdf,
    # fallback to render_html.
    if (modules.module.current_test or tools.config['test_enable']) and not self.env.context.get('force_report_rendering'):
        return self._render_qweb_html(report_ref, res_ids, data=data)

    self = self.with_context(webp_as_jpg=True)
    return self._render_qweb_pdf_prepare_streams(report_ref, data, res_ids=res_ids), 'pdf'


def _render_qweb_pdf(self, report_ref, res_ids=None, data=None):
    if not data:
        data = {}
    if isinstance(res_ids, int):
        res_ids = [res_ids]
    data.setdefault('report_type', 'pdf')

    collected_streams, report_type = self._pre_render_qweb_pdf(report_ref, res_ids=res_ids, data=data)
    if report_type != 'pdf':
        return collected_streams, report_type

    has_duplicated_ids = res_ids and len(res_ids) != len(set(res_ids))

    # access the report details with sudo() but keep evaluation context as current user
    report_sudo = self._get_report(report_ref)

    # Generate the ir.attachment if needed.
    if not has_duplicated_ids and report_sudo.attachment and not self.env.context.get("report_pdf_no_attachment"):
        attachment_vals_list = self._prepare_pdf_report_attachment_vals_list(report_sudo, collected_streams)
        if attachment_vals_list:
            attachment_names = ', '.join(x['name'] for x in attachment_vals_list)
            try:
                self.env['ir.attachment'].create(attachment_vals_list)
            except AccessError:
                _logger.info("Cannot save PDF report %r attachments for user %r", attachment_names, self.env.user.display_name)
            else:
                _logger.info("The PDF documents %r are now saved in the database", attachment_names)

    def custom_handle_merge_pdfs_error(error, error_stream):
        error_record_ids.append(stream_to_ids[error_stream])

    stream_to_ids = {v['stream']: k for k, v in collected_streams.items() if v['stream']}
    # Merge all streams together for a single record.
    streams_to_merge = list(stream_to_ids.keys())
    error_record_ids = []

    if len(streams_to_merge) == 1:
        pdf_content = streams_to_merge[0].getvalue()
    else:
        with self._merge_pdfs(streams_to_merge, custom_handle_merge_pdfs_error) as pdf_merged_stream:
            pdf_content = pdf_merged_stream.getvalue()

    if error_record_ids:
        action = {
            'type': 'ir.actions.act_window',
            'name': _('Problematic record(s)'),
            'res_model': report_sudo.model,
            'domain': [('id', 'in', error_record_ids)],
            'views': [(False, 'list'), (False, 'form')],
        }
        num_errors = len(error_record_ids)
        if num_errors == 1:
            action.update({
                'views': [(False, 'form')],
                'res_id': error_record_ids[0],
            })
        raise RedirectWarning(
            message=_('Odoo is unable to merge the generated PDFs because of %(num_errors)s corrupted file(s)', num_errors=num_errors),
            action=action,
            button_text=_('View Problematic Record(s)'),
        )

    for stream in streams_to_merge:
        stream.close()

    if res_ids:
        _logger.info("The PDF report has been generated for model: %s, records %s.", report_sudo.model, str(res_ids))

    return pdf_content, 'pdf'


def _get_pdf_engine(self, report=None, default_engine='wkhtmltopdf') -> str:
    """Resolve the PDF engine name from report settings and db's fallback.

        This helper is shared by modules that manually call low-level PDF rendering
        methods and still use account reports.
        """
    report_type = (getattr(report, 'report_type', '') or '').lower()
    engine_name = (
        report_type.removeprefix('qweb-pdf-')
        if report_type.startswith('qweb-pdf-')
        else self.env['ir.config_parameter'].sudo().get_str('report.pdf_engine_default') or 'html'
        )  # Low-level PDF rendering methods require an explicit PDF engine.
    return engine_name if engine_name and engine_name != 'html' else default_engine


def _run_image_engine(self, engine_name: str, bodies: Sequence[str], width: int, height: int, image_format: str = "jpg") -> list[bytes | None]:
    """ Render an image using a PDF engine.

        :param engine_name: the name of the image rendering engine to use
        :param bodies: valid html documents as strings
        :param width: width in pixels
        :param height: height in pixels
        :param image_format: format of the image (usually jpg or png)
        """
    e = NotImplementedError("No image rendering engine installed")
    raise e


def _run_pdf_engine(
    self,
    engine_name: str,
    html: str,
    report_ref: str | typing.Literal[False] = False,
    landscape: bool = False,
    **kwargs,
) -> tuple[bytes, list[int]]:
    """Render the HTML using the associated PDF engine.

        :param engine_name: The name of the pdf engine to use.
        :param html: The html to convert to pdf.
        :param report_ref: The report reference (opt.).
        :param landscape: If the pdf should be in landscape mode (opt.).
        :param kwargs: Additional arguments to pass to the pdf engine. (e.g. page size, margins, etc.)
        :return: a tuple of (pdf, html_ids) where pdf is the generated pdf content and html ids to separate the
            pdf content.
        """
    # If we reach here it means no module handled the pdf rendering with the given engine_name.
    e = NotImplementedError(f"Unknown PDF engine: {engine_name}")
    raise e


def _run_pdf_engine_without_processing(
    self,
    engine_name: str,
    bodies: Sequence[str],
    report_ref: str | typing.Literal[False] = False,
    *,
    header: str | None = None,
    footer: str | None = None,
    landscape: bool = False,
    specific_paperformat_args: dict | None = None,
    **kwargs,
) -> bytes:
    # If we reach here it means no module handled the pdf rendering with the given engine_name.
    e = NotImplementedError(f"Unknown PDF engine: {engine_name}")
    raise e


def _render(self, report_ref, res_ids, data=None):
    report = self._get_report(report_ref)
    report_type = report.report_type.lower().replace('-', '_')
    render_func = getattr(self, '_render_' + report_type, None)
    if not render_func:
        return None
    return render_func(report_ref, res_ids, data=data)


def _prepare_local_attachments(self, attachments):
    for attachment in attachments:
        if attachment._is_remote_source():
            try:
                attachment._migrate_remote_to_local()
            except (ValidationError, requests.exceptions.RequestException) as e:
                _logger.error("Failed to migrate attachment %s to local: %s", attachment.id, e)
    return attachments.filtered(lambda a: not a._is_remote_source())
