#!/usr/bin/env python3
"""Minimal MVP of the Odoo-like architecture.

- A model registry: models declare Field objects as class attributes.
- A storage layer: one SQLite table per model.
- A REST-style endpoint: POST /json/2/<model>/<method> with a plain JSON body of named
  parameters (no JSON-RPC envelope).
- A static web client served from ../web.

Usage: python3 app.py --db mvp.sqlite --port 8090
"""
import argparse
import json
import mimetypes
import sqlite3
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent.parent
WEB_DIR = ROOT / 'web'
REGISTRY = {}
SQL_TYPES = {'char': 'TEXT', 'text': 'TEXT', 'selection': 'TEXT', 'float': 'REAL', 'boolean': 'INTEGER'}
OPERATORS = {'=': '=', '!=': '!=', 'ilike': 'LIKE'}
API_METHODS = {'fields_get', 'search_read', 'create', 'write', 'unlink'}


class UserError(Exception):
    """An error caused by the request, reported to the client with HTTP 400."""


class Field:
    def __init__(self, type, string=None, required=False, default=None, selection=None):
        if type not in SQL_TYPES:
            raise ValueError(f"unknown field type {type!r}")
        self.type = type
        self.string = string
        self.required = required
        self.default = default
        self.selection = selection or []
        self.name = None


class ModelMeta(type):
    def __new__(mcls, name, bases, namespace):
        cls = super().__new__(mcls, name, bases, namespace)
        cls._fields = {}
        for key, value in namespace.items():
            if isinstance(value, Field):
                value.name = key
                cls._fields[key] = value
        if namespace.get('_name'):
            REGISTRY[namespace['_name']] = cls
            cls._table = namespace['_name'].replace('.', '_')
        return cls


class Model(metaclass=ModelMeta):
    """Base class. Every method receives the database connection as ``db``."""
    _name = None
    _table = None

    @classmethod
    def create_table(cls, db):
        columns = ['id INTEGER PRIMARY KEY AUTOINCREMENT']
        columns += [f'{name} {SQL_TYPES[field.type]}' for name, field in cls._fields.items()]
        db.execute(f'CREATE TABLE IF NOT EXISTS {cls._table} ({", ".join(columns)})')

    @classmethod
    def fields_get(cls, db):
        return {
            name: {
                'type': field.type,
                'string': field.string or name,
                'required': field.required,
                'selection': [list(option) for option in field.selection],
            }
            for name, field in cls._fields.items()
        }

    @classmethod
    def search_read(cls, db, domain=None, fields=None, offset=0, limit=None, order=None):
        where, params = cls._domain_sql(domain or [])
        columns = ['id'] + cls._check_fields(fields or list(cls._fields))
        sql = f'SELECT {", ".join(columns)} FROM {cls._table}{where} ORDER BY {cls._check_order(order)}'
        if limit is not None:
            sql += ' LIMIT ? OFFSET ?'
            params += [int(limit), int(offset)]
        return [dict(row) for row in db.execute(sql, params).fetchall()]

    @classmethod
    def create(cls, db, vals):
        values = cls._clean_values(vals, creating=True)
        names = list(values)
        sql = f'INSERT INTO {cls._table} ({", ".join(names)}) VALUES ({", ".join("?" * len(names))})'
        cursor = db.execute(sql, [values[name] for name in names])
        return cursor.lastrowid

    @classmethod
    def write(cls, db, ids, vals):
        values = cls._clean_values(vals, creating=False)
        if not values or not ids:
            return True
        assignments = ', '.join(f'{name} = ?' for name in values)
        marks = ', '.join('?' * len(ids))
        db.execute(
            f'UPDATE {cls._table} SET {assignments} WHERE id IN ({marks})',
            [*values.values(), *map(int, ids)],
        )
        return True

    @classmethod
    def unlink(cls, db, ids):
        marks = ', '.join('?' * len(ids))
        db.execute(f'DELETE FROM {cls._table} WHERE id IN ({marks})', [*map(int, ids)])
        return True

    # Helpers -----------------------------------------------------------------

    @classmethod
    def _check_fields(cls, names):
        unknown = [name for name in names if name not in cls._fields]
        if unknown:
            raise UserError(f"unknown field(s) on {cls._name}: {', '.join(unknown)}")
        return list(names)

    @classmethod
    def _check_order(cls, order):
        if not order:
            return 'id'
        name, _, direction = order.partition(' ')
        cls._check_fields([name])
        return f'{name} {"DESC" if direction.strip().lower() == "desc" else "ASC"}'

    @classmethod
    def _domain_sql(cls, domain):
        clauses, params = [], []
        for leaf in domain:
            if not (isinstance(leaf, (list, tuple)) and len(leaf) == 3):
                raise UserError(f"invalid domain leaf {leaf!r}")
            name, operator, value = leaf
            cls._check_fields([name])
            if operator not in OPERATORS:
                raise UserError(f"unsupported operator {operator!r}")
            if operator == 'ilike':
                value = f'%{value}%'
            clauses.append(f'{name} {OPERATORS[operator]} ?')
            params.append(value)
        return (' WHERE ' + ' AND '.join(clauses) if clauses else ''), params

    @classmethod
    def _clean_values(cls, vals, creating):
        cls._check_fields(list(vals))
        values = {}
        for name, value in vals.items():
            field = cls._fields[name]
            if value is None or value is False and field.type != 'boolean':
                values[name] = None
            elif field.type == 'float':
                values[name] = float(value)
            elif field.type == 'boolean':
                values[name] = 1 if value else 0
            elif field.type == 'selection':
                allowed = [option[0] for option in field.selection]
                if value not in allowed:
                    raise UserError(f"{value!r} is not a valid choice for {name}")
                values[name] = value
            else:
                values[name] = str(value)
        if creating:
            for name, field in cls._fields.items():
                if name not in values and field.default is not None:
                    values[name] = field.default
            for name, field in cls._fields.items():
                if field.required and not values.get(name) and values.get(name) != 0:
                    raise UserError(f"field {name} is required")
        return values


class Env:
    """One database connection per request: the transaction is committed or rolled back."""

    def __init__(self, path):
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row

    def __enter__(self):
        return self.db

    def __exit__(self, exc_type, exc, tb):
        if exc_type is None:
            self.db.commit()
        else:
            self.db.rollback()
        self.db.close()


def init_database(path):
    with Env(path) as db:
        for model in REGISTRY.values():
            model.create_table(db)


def call_api(path, body, db_path):
    """Dispatch POST /json/2/<model>/<method>. Returns the JSON result."""
    parts = [part for part in path.split('/') if part]
    if len(parts) != 4 or parts[:2] != ['json', '2']:
        raise LookupError(f"no endpoint at {path}")
    model_name, method = parts[2], parts[3]
    if model_name not in REGISTRY or method not in API_METHODS:
        raise LookupError(f"no endpoint at {path}")
    if not isinstance(body, dict):
        raise UserError("the body must be a JSON object of named parameters")
    with Env(db_path) as db:
        try:
            return getattr(REGISTRY[model_name], method)(db, **body)
        except TypeError as error:
            raise UserError(f"invalid parameters for {method}: {error}") from error


class Handler(BaseHTTPRequestHandler):
    db_path = None

    def do_POST(self):
        path = urlparse(self.path).path
        if not path.startswith('/json/2/'):
            return self._send_json(404, {'error': {'message': 'not found'}})
        try:
            length = int(self.headers.get('Content-Length') or 0)
            body = json.loads(self.rfile.read(length) or b'{}')
            result = call_api(path, body, self.db_path)
        except LookupError as error:
            return self._send_json(404, {'error': {'message': str(error)}})
        except UserError as error:
            return self._send_json(400, {'error': {'message': str(error), 'type': 'user_error'}})
        except json.JSONDecodeError as error:
            return self._send_json(400, {'error': {'message': f'invalid JSON: {error}'}})
        self._send_json(200, result)

    def do_GET(self):
        path = urlparse(self.path).path
        target = WEB_DIR / ('index.html' if path in ('', '/') else path.lstrip('/'))
        if not target.resolve().is_relative_to(WEB_DIR.resolve()) or not target.is_file():
            return self._send_json(404, {'error': {'message': 'not found'}})
        content_type = mimetypes.guess_type(target.name)[0] or 'application/octet-stream'
        data = target.read_bytes()
        self.send_response(200)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _send_json(self, status, payload):
        data = json.dumps(payload, ensure_ascii=False, default=str).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, format, *args):
        pass


class Task(Model):
    """Demo model used by the web client."""
    _name = 'mvp.task'
    name = Field('char', string='Name', required=True)
    stage = Field('selection', string='Stage', default='todo',
                  selection=[('todo', 'To do'), ('doing', 'In progress'), ('done', 'Done')])
    amount = Field('float', string='Amount', default=0.0)
    description = Field('text', string='Description')


SEED = [
    {'name': 'Prepare quotation', 'stage': 'todo', 'amount': 1200.0, 'description': 'Send to the client by Friday.'},
    {'name': 'Review contract', 'stage': 'doing', 'amount': 5400.5, 'description': ''},
    {'name': 'Ship order #1024', 'stage': 'done', 'amount': 860.0, 'description': 'Delivered.'},
]


def seed_if_empty(path):
    with Env(path) as db:
        if db.execute(f'SELECT COUNT(*) FROM {Task._table}').fetchone()[0] == 0:
            for vals in SEED:
                Task.create(db, vals)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--db', default=str(ROOT / 'mvp.sqlite'))
    parser.add_argument('--port', type=int, default=8090)
    args = parser.parse_args()
    init_database(args.db)
    seed_if_empty(args.db)
    Handler.db_path = args.db
    server = ThreadingHTTPServer(('127.0.0.1', args.port), Handler)
    print(f'MVP running on http://127.0.0.1:{args.port} (database: {args.db})')
    server.serve_forever()


if __name__ == '__main__':
    main()
