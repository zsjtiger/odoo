# Architecture of the web client

The JavaScript, templates and styles of the web client live in
`static/src`. A file's path is also its module name: `static/src/core/x.js`
is the module `@web/core/x`.

## Folders

| Layer | Folder       | Content                                                         |
|-------|--------------|-----------------------------------------------------------------|
| 0     | `core/`      | Framework kernel, depends on nothing else of web                |
| 0     | `libs/`      | Wrappers of third-party libraries                               |
| 1     | `search/`    | Search model, control panel, search bar and panel               |
| 1     | `public/`    | Pages outside of the web client: login, database manager        |
| 2     | `model/`     | Data model of the views: records, relational model              |
| 3     | `views/`     | Views and their building blocks, field widgets                  |
| 4     | `webclient/` | Application shell: navbar, menus, actions                       |
| 5     | `boot/`      | Startup: module loader, entry points, session, polyfills        |

`scss/` holds the global styles and `@types/` the type declarations.

### core/

| Folder        | Content                                                       |
|---------------|---------------------------------------------------------------|
| `framework/`  | Registries, services, templates, assets loading               |
| `services/`   | Services and plugins started with the web client              |
| `data/`       | Domains, contexts, Python expressions, localization           |
| `components/` | Generic UI components                                          |
| `dialogs/`    | Dialogs                                                        |
| `editors/`    | Domain, expression and field selection editors                 |
| `owl/`        | Owl 2 compatibility layer on top of Owl 3                      |
| `utils/`      | Pure helpers                                                   |

### views/fields/

Field widgets are grouped by kind: `text/`, `numeric/`, `boolean/`,
`date/`, `selection/`, `relational/`, `media/` and `special/`. The base
classes and helpers shared by all the fields are at the root of `fields/`.

### scss/

`bootstrap/` imports and adapts Bootstrap, `variables/` defines the
variables (loaded in order: pre, primary, secondary). The shared functions
and the global styles are at the root.

## Rules

- A folder only imports the folders of its layer and of the lower layers.
  `boot/session` and `boot/env` are leaf modules that every layer may use.
- The tests of `static/tests` mirror the folders of `static/src`.

Both rules, the existence of every imported module and the asset paths of
the manifests are checked by `setup/check_web_frontend.py`.

## Moving files

`setup/web_layout.py` describes where each file goes and
`setup/move_web_files.py` applies it: it moves the files and rewrites
their module names, asset paths and relative imports in the repository.
An addon written for the former layout is updated with:

    setup/move_web_files.py --port path/to/addon
