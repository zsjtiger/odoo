# -*- coding: utf-8 -*-
"""Excel reading and writing for data import (openpyxl). No models here.

Layout of every import file:
    row 1  header labels (what the user reads)
    row 2  technical names (what the import matches on): action, id, record_type, field names
    row 3+ data rows
"""
import io

from openpyxl import Workbook, load_workbook
from openpyxl.comments import Comment
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation

HEADER_ROW = 1
TECH_ROW = 2
DATA_START_ROW = 3
RESULT_HEADER = 'Validation Error'
RESULT_TECH = 'validation_error'
MAX_DV_FORMULA = 255


def _fill(color):
    code = color.lstrip('#').upper()
    return PatternFill(start_color=code, end_color=code, fill_type='solid')


def _align(value):
    return Alignment(horizontal=value or 'left', vertical='center')


def build_template(columns, style, example=None, help_rows=None):
    """Return the bytes of a template workbook.

    columns: list of dicts with name, header, required, width, align, number_format,
             options (list of str for a dropdown or None), hidden, note, example.
    style:   dict with sheet_name, header_font_color, header_fill_color, header_bold,
             header_height, freeze_header, show_gridlines, action_fill_color,
             required_fill_color, show_help_sheet, help_sheet_name.
    help_rows: list of tuples written to the Help sheet (first tuple is the header).
    """
    wb = Workbook()
    ws = wb.active
    ws.title = (style.get('sheet_name') or 'Import')[:31]
    ws.sheet_view.showGridLines = style.get('show_gridlines', True)
    header_font = Font(bold=style.get('header_bold', True), color=style.get('header_font_color', '#FFFFFF').lstrip('#'))
    tech_font = Font(italic=True, color='7F7F7F', size=9)
    for index, col in enumerate(columns, start=1):
        letter = get_column_letter(index)
        header_fill = style.get('required_fill_color') if col.get('required') else style.get('header_fill_color')
        cell = ws.cell(row=HEADER_ROW, column=index, value=col['header'])
        cell.font = header_font
        cell.fill = _fill(header_fill or '#0E7C86')
        cell.alignment = Alignment(horizontal='center', vertical='center', wrap_text=True)
        if col.get('note'):
            cell.comment = Comment(col['note'], 'Data Import')
        ws.cell(row=TECH_ROW, column=index, value=col['name']).font = tech_font
        ws.column_dimensions[letter].width = col.get('width') or 14
        ws.column_dimensions[letter].hidden = bool(col.get('hidden'))
        if col['name'] == 'action':
            ws.column_dimensions[letter].width = 10
        options = col.get('options')
        if options is None and col['name'] == 'action':
            options = ['N', 'U', 'D']
        if options:
            joined = ','.join(str(o).replace(',', ' ') for o in options)
            if len(joined) <= MAX_DV_FORMULA:
                dv = DataValidation(type='list', formula1=f'"{joined}"', allow_blank=True)
                dv.add(f'{letter}{DATA_START_ROW}:{letter}2000')
                ws.add_data_validation(dv)
        if col['name'] == 'action':
            for row in range(DATA_START_ROW, 2001):
                ws.cell(row=row, column=index).fill = _fill(style.get('action_fill_color') or '#FFF2CC')
    if example:
        for index, col in enumerate(columns, start=1):
            value = example.get(col['name'])
            if value not in (None, ''):
                ws.cell(row=DATA_START_ROW, column=index, value=value).alignment = _align(columns[index - 1].get('align'))
    ws.row_dimensions[HEADER_ROW].height = style.get('header_height', 24)
    if style.get('freeze_header', True):
        ws.freeze_panes = f'A{DATA_START_ROW}'
    if style.get('show_help_sheet', True) and help_rows:
        help_ws = wb.create_sheet((style.get('help_sheet_name') or 'Help')[:31])
        for r, row in enumerate(help_rows, start=1):
            for c, value in enumerate(row, start=1):
                cell = help_ws.cell(row=r, column=c, value=value)
                if r == 1:
                    cell.font = Font(bold=True)
        for c in range(1, len(help_rows[0]) + 1):
            help_ws.column_dimensions[get_column_letter(c)].width = 28
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


def read_upload(content):
    """Return (tech_names, rows). rows is a list of (sheet_row_number, {tech_name: value})."""
    wb = load_workbook(io.BytesIO(content), data_only=True)
    ws = wb.worksheets[0]
    tech = []
    for cell in ws[TECH_ROW]:
        tech.append(str(cell.value).strip() if cell.value not in (None, '') else None)
    while tech and tech[-1] is None:
        tech.pop()
    rows = []
    if not tech:
        return tech, rows
    for row_number, cells in enumerate(
        ws.iter_rows(min_row=DATA_START_ROW, max_col=len(tech), values_only=True),
        start=DATA_START_ROW,
    ):
        if all(v in (None, '') for v in cells):
            continue
        rows.append((row_number, {name: value for name, value in zip(tech, cells) if name}))
    return tech, rows


def write_result(content, tech_count, errors):
    """Return the bytes of the uploaded file with a Validation Error column appended."""
    wb = load_workbook(io.BytesIO(content))
    ws = wb.worksheets[0]
    col = tech_count + 1
    letter = get_column_letter(col)
    header = ws.cell(row=HEADER_ROW, column=col, value=RESULT_HEADER)
    header.font = Font(bold=True, color='FFFFFF')
    header.fill = _fill('#C0392B')
    ws.cell(row=TECH_ROW, column=col, value=RESULT_TECH).font = Font(italic=True, color='7F7F7F', size=9)
    ws.column_dimensions[letter].width = 60
    for row_number, message in errors.items():
        ws.cell(row=row_number, column=col, value=message).font = Font(color='C0392B')
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()
