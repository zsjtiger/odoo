# -*- coding: utf-8 -*-
import ast
import base64
import logging
from datetime import date, datetime

from odoo import api, fields, models, _
from odoo.exceptions import AccessError, UserError

from ..xlsx_io import DATA_START_ROW, read_upload, write_result
from .ir_data_import_template import RESERVED_COLUMNS

_logger = logging.getLogger(__name__)

MAX_ROWS = 2000
ACTIONS = ('N', 'U', 'D')
TRUE_TEXT = {'1', 'true', 'yes', 'y', '是', '对'}
FALSE_TEXT = {'0', 'false', 'no', 'n', '否', '错'}


class _Rollback(Exception):
    """Raised to undo every change of a run that must not be kept."""


class IrDataImportJob(models.Model):
    _name = 'ir.data.import.job'
    _description = 'Data Import Job'
    _order = 'id desc'

    user_id = fields.Many2one('res.users', required=True, readonly=True, default=lambda self: self.env.user)
    model_id = fields.Many2one('ir.model', required=True, readonly=True, ondelete='cascade')
    model_name = fields.Char(related='model_id.model', readonly=True)
    state = fields.Selection([
        ('draft', 'Draft'), ('validated', 'Validated'), ('done', 'Done'),
    ], default='draft', readonly=True)
    source_file = fields.Binary(string='Uploaded file', attachment=True, readonly=True)
    source_filename = fields.Char(readonly=True)
    result_file = fields.Binary(string='Result file', attachment=True, readonly=True)
    result_filename = fields.Char(readonly=True)
    total_rows = fields.Integer(readonly=True)
    error_rows = fields.Integer(readonly=True)
    created_rows = fields.Integer(readonly=True)
    updated_rows = fields.Integer(readonly=True)
    deleted_rows = fields.Integer(readonly=True)
    message = fields.Text(readonly=True)
    record_type_id = fields.Many2one(
        'ir.record.type', string='Default record type', readonly=True,
        help='Used for new rows that do not name a record type.',
    )

    # ------------------------------------------------------------------ entry points

    def action_validate(self):
        """Check every row and store the result file. Nothing is kept in the database."""
        self.ensure_one()
        return self._run(commit=False)

    def action_import(self):
        """Import the file. All rows are applied, or none if any row has an error."""
        self.ensure_one()
        if self.state != 'validated' or self.error_rows:
            raise UserError(_('Validate the file and fix every error before importing.'))
        return self._run(commit=True)

    # ------------------------------------------------------------------ run

    def _run(self, commit):
        self.ensure_one()
        perm = self.env['ir.data.import.permission']
        if not perm._user_can(self.model_name, 'allow_import'):
            raise AccessError(_('You are not allowed to import %s.', self.model_id.name))
        if not self.source_file:
            raise UserError(_('No file uploaded.'))
        content = bytes(self.source_file)  # Binary fields are read as raw bytes
        try:
            tech, rows = read_upload(content)
        except Exception as exc:  # openpyxl raises several error types for broken files
            raise UserError(_('The file is not a valid Excel (.xlsx) file.')) from exc
        if 'action' not in tech:  # the column order does not matter; the names do
            raise UserError(_('The file does not match the template. Download the template and use it.'))
        if len(rows) > MAX_ROWS:
            raise UserError(_('The file has %(rows)s rows; the limit is %(limit)s rows per import.',
                              rows=len(rows), limit=MAX_ROWS))

        Model = self.env[self.model_name]
        errors = {}
        counts = {'N': 0, 'U': 0, 'D': 0}
        seen = set()
        cache = {}
        try:
            with self.env.cr.savepoint():
                for row_number, row in rows:
                    try:
                        with self.env.cr.savepoint():
                            action = self._process_row(row, Model, seen, cache)
                        counts[action] += 1
                    except Exception as exc:  # one bad row must not stop the others
                        errors[row_number] = self._error_text(exc, row_number)
                if commit and not errors:
                    pass  # keep the changes: the savepoint is released
                else:
                    raise _Rollback()
        except _Rollback:
            pass
        self.env.invalidate_all()

        result = write_result(content, len(tech), errors)
        done = commit and not errors
        self.write({
            'state': 'done' if done else 'validated',
            'total_rows': len(rows),
            'error_rows': len(errors),
            'created_rows': counts['N'] if done else 0,
            'updated_rows': counts['U'] if done else 0,
            'deleted_rows': counts['D'] if done else 0,
            'result_file': base64.b64encode(result).decode(),
            'result_filename': f'{self.model_name}_result.xlsx',
            'message': (_('Import stopped: %s row(s) have errors. Nothing was imported.', len(errors))
                        if commit and errors else False),
        })
        return True

    def _error_text(self, exc, row_number):
        if isinstance(exc, UserError | AccessError):
            return str(exc.args[0]) if exc.args else str(exc)
        _logger.exception('Data import: unexpected error on row %s', row_number)
        return _('Unexpected error: %s', exc)

    # ------------------------------------------------------------------ one row

    def _process_row(self, row, Model, seen, cache):
        action = str(row.get('action') or '').strip().upper()
        if action not in ACTIONS:
            raise UserError(_('Action must be N (new), U (update) or D (delete).'))
        rec_id = self._resolve_id(Model, row.get('id'))
        record_type = self._resolve_record_type(Model, row.get('record_type'))
        if not record_type and action == 'N' and self.record_type_id:
            record_type = self.record_type_id
        values = self._convert_values(Model, row)

        if action == 'N':
            if rec_id:
                raise UserError(_('Leave ID empty for new records.'))
            self._check_required(Model, record_type, values, cache)
            if not record_type and self._has_record_types(Model):
                record_type = self.env['ir.record.type']._get_default_for_user(Model._name)
            if record_type:
                record_type._check_import_allowed()
                values['record_type_id'] = record_type.id
            record = Model.create(values)
        else:
            if not rec_id:
                raise UserError(_('ID is required for %s rows.', action))
            if rec_id in seen:
                raise UserError(_('ID %s appears more than once in the file.', rec_id))
            seen.add(rec_id)
            record = Model.browse(rec_id)
            if not record.exists():
                raise UserError(_('ID %s does not exist.', rec_id))
            if self._has_record_types(Model) and record.record_type_id:
                record.record_type_id._check_import_allowed()  # the type the record has now
            if action == 'U':
                if record_type:
                    record_type._check_import_allowed()  # the type the record moves to
                    values['record_type_id'] = record_type.id
                if values:
                    record.write(values)

        if action in ('N', 'U'):
            self._check_rules(record, action)
            hook = getattr(record, '_import_validate_row', None)
            if hook:
                hook(action, values, record)
        else:
            hook = getattr(record, '_import_validate_row', None)
            if hook:
                hook(action, values, record)
            if 'record_type_id' in Model._fields and record.record_type_id:
                record.record_type_id._check_can_use(Model._name, 'unlink')
            record.unlink()
        return action

    # ------------------------------------------------------------------ helpers

    def _has_record_types(self, Model):
        return 'record_type_id' in Model._fields and hasattr(Model, '_record_type_enabled') \
            and Model._record_type_enabled()

    def _resolve_id(self, Model, raw):
        if raw in (None, ''):
            return None
        if isinstance(raw, float) and raw.is_integer():
            raw = int(raw)
        if isinstance(raw, int) and not isinstance(raw, bool):
            return raw
        text = str(raw).strip()
        if text.isdigit():
            return int(text)
        if '.' in text:
            ref = self.env.ref(text, raise_if_not_found=False)
            if ref and ref._name == Model._name:
                return ref.id
        raise UserError(_('ID "%s" not found.', text))

    def _resolve_record_type(self, Model, raw):
        if raw in (None, ''):
            return None
        text = self._as_text(raw)
        if not self._has_record_types(Model):
            raise UserError(_('This model has no record types.'))
        types = self.env['ir.record.type'].search([
            ('model_name', '=', Model._name), '|', ('code', '=', text), ('name', '=', text),
        ], limit=2)
        if not types:
            raise UserError(_('Record type "%s" not found.', text))
        if len(types) > 1:
            raise UserError(_('Record type "%s" matches more than one type; use the code.', text))
        return types

    def _convert_values(self, Model, row):
        values = {}
        for name, raw in row.items():
            if name in RESERVED_COLUMNS or raw in (None, ''):
                continue
            field = Model._fields.get(name)
            if not field:
                raise UserError(_('Unknown column "%s".', name))
            if field.type in ('one2many', 'many2many', 'binary', 'properties', 'reference') or not field.store:
                raise UserError(_('Field "%s" cannot be imported.', field.string))
            values[name] = self._convert_value(field, raw)
        return values

    def _convert_value(self, field, raw):
        label = field.string
        kind = field.type
        if kind in ('char', 'text', 'html'):
            return self._as_text(raw)
        if kind == 'integer':
            try:
                return int(float(raw))
            except (TypeError, ValueError):
                raise UserError(_('%s must be a whole number.', label)) from None
        if kind in ('float', 'monetary'):
            try:
                return float(raw)
            except (TypeError, ValueError):
                raise UserError(_('%s must be a number.', label)) from None
        if kind == 'boolean':
            text = self._as_text(raw).lower()
            if text in TRUE_TEXT:
                return True
            if text in FALSE_TEXT:
                return False
            raise UserError(_('%s must be Yes or No.', label))
        if kind == 'date':
            if isinstance(raw, datetime):
                return raw.date()
            if isinstance(raw, date):
                return raw
            try:
                return fields.Date.from_string(self._as_text(raw))
            except ValueError:
                raise UserError(_('%s must be a date like 2026-12-31.', label)) from None
        if kind == 'datetime':
            if isinstance(raw, datetime):
                return raw.replace(tzinfo=None)
            try:
                return fields.Datetime.from_string(self._as_text(raw))
            except ValueError:
                raise UserError(_('%s must be a date and time like 2026-12-31 18:00:00.', label)) from None
        if kind == 'selection':
            text = self._as_text(raw)
            for value, option in field._description_selection(self.env):
                if text in (str(value), str(option)):
                    return value
            raise UserError(_('%(label)s: "%(value)s" is not an allowed option.', label=label, value=text))
        if kind == 'many2one':
            return self._find_many2one(field, raw)
        raise UserError(_('Field "%s" cannot be imported.', label))

    def _find_many2one(self, field, raw):
        comodel = self.env[field.comodel_name]
        text = self._as_text(raw)
        if '.' in text:
            ref = self.env.ref(text, raise_if_not_found=False)
            if ref and ref._name == comodel._name:
                return ref.id
        rec_name = comodel._rec_name or 'name'
        found = comodel.search([(rec_name, '=', text)], limit=2)
        if not found:
            raise UserError(_('%(label)s: "%(value)s" not found.', label=field.string, value=text))
        if len(found) > 1:
            raise UserError(_('%(label)s: "%(value)s" matches several records; use the external ID.',
                              label=field.string, value=text))
        return found.id

    @staticmethod
    def _as_text(raw):
        if isinstance(raw, float) and raw.is_integer():
            return str(int(raw))
        return str(raw).strip() if raw is not None else ''

    def _check_required(self, Model, record_type, values, cache):
        key = (Model._name, record_type.id if record_type else False)
        if key not in cache:
            template = self.env['ir.data.import.template']._find_template(Model._name, record_type)
            cache[key] = template.sudo().column_ids.filtered('required_on_create') if template else []
        for column in cache[key]:
            if values.get(column.field_id.name) in (None, False, ''):
                raise UserError(_('%s is required.', column.header or column.field_id.field_description))

    def _check_rules(self, record, action):
        model = self.env['ir.model'].sudo()._get(self.model_name)
        rules = self.env['ir.data.import.rule'].search([
            ('model_id', '=', model.id), ('active', '=', True),
            ('action', 'in', ['all', action]),
        ])
        for rule in rules:
            if rule.record_type_id and 'record_type_id' in record._fields \
                    and record.record_type_id != rule.record_type_id:
                continue
            domain = ast.literal_eval(rule.domain or '[]')
            if not record.filtered_domain(domain):
                raise UserError(rule.message)
