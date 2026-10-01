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
| L5    | `cli`      | Command line: `odoo-bin` sub-commands and developer tools       |
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

    odoo-bin | python -m odoo | odoo (console script)
     └─ odoo.cli.main()
         ├─ odoo.core.bootstrap      python checks, gc tuning, library patches
         ├─ odoo.orm                 shortcuts on the `odoo` namespace
         └─ odoo.cli.server          configuration, logging, database checks
             └─ odoo.service.server.start()
                 ├─ load the server-wide modules
                 ├─ pick the server: gevent, prefork or threaded
                 └─ preload the registries and serve

Importing `odoo.orm`, `odoo.modules`, `odoo.http` or `odoo.cli` runs the
bootstrap, so the framework also works when used as a library.

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
| `odoo.sql_db`                | `odoo.orm.sql_db`           |
| `odoo.tools.cache`           | `odoo.orm.cache`            |
| `odoo.tools.view_validation` | `odoo.orm.view_validation`  |
| `odoo.tools.cloc`            | `odoo.modules.cloc`         |
| `odoo.tools.duplicate`       | `odoo.cli.duplicate`        |
| `odoo.upgrade_code`          | `odoo.cli.upgrade_code`     |
