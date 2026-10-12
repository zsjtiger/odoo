# Architecture of the Odoo core

The `odoo` directory holds the framework. Business features live in addons,
under `addons/` and `odoo/addons/`; they only use the public API below.

## Packages

| Layer | Package    | Responsibility                                                  |
|-------|------------|-----------------------------------------------------------------|
| L0    | `tools`    | Utilities: configuration, SQL builder, text, files, i18n, ...   |
| L1    | `core`     | Server infrastructure: bootstrap, library patches, logging      |
| L2    | `orm`      | Database access (`sql_db`), models, fields, environments        |
| L3    | `modules`  | Module system: manifests, loading, migrations, registry         |
| L4    | `http`     | Web framework: routing, requests, sessions, responses           |
| L4    | `service`  | RPC services and server processes (threaded, prefork, gevent)   |
| L5    | `cli`      | Command line: `cross-cli.py` sub-commands and developer tools       |
| L5    | `tests`    | Test framework                                                  |

`release` and `exceptions` belong to L0. `api`, `fields` and `models` are
thin facades over `orm` (L2).

## Public API

Addons import from `odoo.api`, `odoo.fields`, `odoo.models`, `odoo.tools`,
`odoo.http`, `odoo.exceptions` and `odoo.tests`, plus the shortcuts `odoo._`,
`odoo._lt`, `odoo.Command` and `odoo.SUPERUSER_ID`.

## Dependency rule

A module only imports modules of its own layer and of lower layers when it is
loaded. Imports of upper layers are allowed inside functions and inside
`if TYPE_CHECKING:` blocks. The rule is checked by:

    setup/check_layers.py

## Startup

    cross-cli.py | python -m odoo
     └─ odoo.cli.main()
         ├─ odoo.core.bootstrap      python checks, gc tuning, library patches
         ├─ odoo.orm                 shortcuts on the `odoo` namespace
         └─ odoo.cli.commands.server  configuration, logging, database checks
             └─ odoo.service.server.start()
                 ├─ load the server-wide modules
                 ├─ pick the server: gevent, prefork or threaded
                 └─ preload the registries and serve

Importing `odoo.orm`, `odoo.modules`, `odoo.http` or `odoo.cli` runs the
bootstrap, so the framework also works when used as a library.

## Layout of the packages

Packages that were split by concern keep their import path; the modules inside
are named after their responsibility:

- `orm/models/`: `BaseModel` (`__init__`), the registry, the environments and
  the caches; the methods of `BaseModel` delegate to one module per concern
  (`search`, `read`, `create`, `write`, `grouping`, `export`, `recompute`...).
- `orm/fields/`: `Field` (`__init__`) and one module per field family.
- `orm/database/`: the SQL cursors, the queries, the table objects and the schema.
- `orm/core/`: access rights, commands, decorators, identifiers and utils. `domains/`
  is a package: `constants` (operators and levels), `registry` (the optimization
  decorators), `classes` (the `Domain` classes), and `optimizations/` (one module per
  topic; importing them registers them, in a fixed order).
- `tools/`: the shared helpers at the top level; `text`, `files`, `numeric`,
  `sql`, `xml`, `loading`, `js`, `profiling` and `system` group the others. The
  modules moved there are not aliased: import them from their new path.
- `service/server/`: `start`/`restart` (`__init__`), `threaded`, `gevent_server`,
  `prefork`, `worker`, `reloader` and the shared base in `common`.
- `tests/common/`: the test framework, one module per concern (`base`,
  `transaction`, `http_case`, `decorators`, `mocks`, `locks`, `utils`). `browser/`
  is a package: `browser` (the `ChromeBrowser` class), `process` (starting Chrome),
  `transport` (devtools HTTP and websocket), `events` (console and exceptions),
  `executable`, `files` and `exceptions`. `odoo.tests.common` re-exports the same
  names as before.
- `core/patches/`: one module per patched library; `_werkzeug_urls` holds the
  URL backport that werkzeug 3.0 needs.
- `tests/form/`: `Form` and its proxies, the values of the x2many fields and the
  helpers. `tests/common/screencast` holds the screencast classes.
- `orm/database/sql_db/`: `cursor`, `pool` and `types` (the connection type and
  the decimal conversion).
- `tools/sql/`: `builder` (the SQL objects), `tables`, `columns`, `constraints`,
  `indexes`, `views` and `rows`.
- `tools/mail/`: `html` (`sanitize`, `plaintext` and `content`), `links` and `addresses`.
- `tools/loading/convert/`: `common`, `xml`, `csv` and `file`.
- `tools/js/js_transpiler/`: `paths`, `imports`, `exports` and `transpile`.
- `tools/profiling/profiler/`: `stack`, `collectors`, `qweb` and `profiler`.
- `tools/safe_eval/runtime/`: `errors`, `transformer` and `whitelist`, which also
  holds the checker, the generator and the monitoring (they depend on each other).
- `modules/db/`: `queries`, `init` and `manage`.
- `tools/text/translate/`: `base` (lazy and stored translations), `html` (XML and
  HTML fields), `extract` (term extraction), `files` (PO, CSV, XML and tar files) and
  `modules` (the readers and the importer of the modules).
- `tools/misc/` and `tools/config/`: the former flat modules, split by concern.

## Moved modules

The modules below have been moved. Their former names remain importable once
the bootstrap has run (see `odoo/core/__init__.py`), and their loggers keep
their former names.

| Former name                  | Current name                |
|------------------------------|-----------------------------|
| `odoo.init`                  | `odoo.core.bootstrap`       |
| `odoo._monkeypatches`        | `odoo.core.patches`         |
| `odoo.netsvc`                | `odoo.core.logging`         |
| `odoo.logging`               | `odoo.core.logging`         |
| `odoo.loglevels`             | `odoo.core.logging`         |
| `odoo.sql_db`                | `odoo.orm.database.sql_db`           |
| `odoo.tools.cache`           | `odoo.orm.models.cache`            |
| `odoo.tools.view_validation` | `odoo.orm.core.view_validation`  |
| `odoo.tools.cloc`            | `odoo.modules.cloc`         |
