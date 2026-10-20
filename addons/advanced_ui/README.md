# Advanced UI

Advanced controls for the Odoo web client. The addon provides:

- **Accordion**: collapsible sections, usable in any component or as a form field
  widget on One2many fields.
- **Lookup**: a many2one dropdown with coloured rows, subtitles, group headers and
  an optional scope selector.

## Accordion

A list of collapsible sections. Each row has a summary that is always visible
and a details area shown only while the row is open. Clicking the summary (or
pressing Enter / Space when it has focus) opens the row. By default, opening a
row closes the others.

### Enabling it

Depend on `advanced_ui` in your addon's manifest:

```python
'depends': ['web', 'advanced_ui'],
```

Then import the component from your JavaScript:

```js
import { Accordion } from "@advanced_ui/accordion/accordion";
```

### Usage

Declare the component in your component class and render it in its template:

```js
import { Component } from "@odoo/owl";
import { Accordion } from "@advanced_ui/accordion/accordion";

export class MyWidget extends Component {
    static template = "my_module.MyWidget";
    static components = { Accordion };

    setup() {
        this.items = [
            { id: "shipping", summary: "Shipping", details: "Delivered in 3 to 5 days." },
            { id: "returns", summary: "Returns", details: "Free returns within 30 days." },
        ];
    }
}
```

```xml
<t t-name="my_module.MyWidget">
    <Accordion items="this.items" openIds="['shipping']"/>
</t>
```

### Props

| Prop       | Type      | Default | Description                                                                 |
|------------|-----------|---------|-----------------------------------------------------------------------------|
| `items`    | `array`   | —       | The rows, each `{ id, summary, details }`. `id` must be unique.             |
| `multiple` | `boolean` | `false` | When `true`, several rows can be open at the same time.                     |
| `openIds`  | `array`   | `[]`    | Ids of the rows open when the control is first rendered.                    |

Each item:

| Key       | Description                                                                                  |
|-----------|----------------------------------------------------------------------------------------------|
| `id`      | Unique identifier, used to track which rows are open.                                        |
| `summary` | Text shown in the row header. Always visible.                                                |
| `details` | Content shown when the row is open. Rendered as text; wrap HTML in `markup()` to render it. |

### Putting fields, lists or One2many in a row

Plain text in `details` is enough for simple cases. For anything richer, pass the
content through the `details` slot. It is rendered only while the row is open, and
it is laid out in columns like a form `<group>`:

```xml
<Accordion items="this.sections" openIds="['lines']">
    <t t-set-slot="details" t-slot-scope="scope">
        <!-- fields, rendered as form group columns -->
        <div class="o_accordion_wide">
            <!-- a list or One2many, spanning the full row -->
        </div>
    </t>
</Accordion>
```

The slot receives the row as `scope.item`, so one slot can serve every row and
branch on `scope.item.id`. Wrap content that should span the whole width in an
element with the class `o_accordion_wide`.

The slot needs an OWL template that renders the accordion, so it is set up in a
component template. To show a single field or a whole One2many in a form view without
writing a component, use the `accordion` field widget below.

### In a form view: the `accordion` field widget

A One2many field can be shown as an accordion directly from the form view, with no
JavaScript. Each line of the relation is a row, and the open row shows the fields of
the inline list:

```xml
<field name="line_ids" widget="accordion" options="{'summary': 'name'}">
    <list>
        <field name="name"/>
        <field name="qty"/>
    </list>
</field>
```

- `widget="accordion"` is valid on `one2many` fields.
- `options="{'summary': 'name'}"` sets the field shown in the row header. It must be a
  char field. Without it, the row header reads `display_name`, which is only shown if
  the inline list loads it.
- The fields of the inline `<list>`, except the summary field, are shown in the
  open row, as a form group. Only the fields listed there are loaded.

Limitations of the current version:

- The fields in a row are read-only and show no labels.
- Nested One2many or list views inside a row are not supported.

### Lookup dropdown for many2one

The `lookup` widget is an opt-in dropdown for many2one fields. Its suggestions are
drawn as rows: a coloured tile with the record's initial, the name, and a subtitle
taken from a field of the related model. The default many2one dropdown is unchanged.

```xml
<field name="partner_id" widget="lookup" options="{'subtitle': 'city', 'group': 'type', 'scope': true}"/>
```

- `subtitle` names a char field of the related model shown under each name. Without
  it, the subtitle is empty.
- `group` names a char field of the related model. The suggestions are split under a
  header for each value of that field, in the order they first appear. Records with an
  empty value go under "Other". Without it, the suggestions are not grouped.
- `scope` (requires `group`) adds a selector above the suggestions. It starts on
  "All" and lists "All" and each group value found in the results. Choosing a value
  keeps only the suggestions of that group, and the search re-runs with the text typed
  so far. The selector is only closed by choosing an entry, not by clicking outside.
- The tile colour is chosen from the record id, so it does not follow the model.

Suggestions come from the field's own model only, so the group headers are values of a
field, not separate models.

### Behaviour

- All rows are closed by default, unless their ids are listed in `openIds`.
- With `multiple` unset, opening a row closes the row that was open.
- With `multiple="true"`, rows toggle independently.
- Clicking anywhere on the row header toggles it, including the caret on the right.
- The header is keyboard accessible: it can be focused and toggled with Enter or Space,
  and it sets `aria-expanded` accordingly.

### Limitations

- `openIds` is read once, when the control is created. Changing it later does not
  change which rows are open.
- The caret on the right is purely visual for now: clicking it only toggles the row.
- `items` is read on render. To update the rows, pass a new array.

### Styling

Styles are in `static/src/accordion/accordion.scss`. The open row uses `$primary`
for its summary text and underline, and the chevron rotates to show the state.
Override the classes `o_accordion`, `o_accordion_item`, `o_accordion_summary`,
`o_accordion_details` or `o_accordion_menu` in your own stylesheet to change the look.
The lookup styles are in `static/src/lookup/lookup_autocomplete.scss`.

### Tests

The unit tests live in `static/tests/` (`accordion.test.js`, `accordion_field.test.js`
and `lookup_field.test.js`). They are JavaScript (Hoot) tests, run in the browser:
install or update the addon on a database, then open `/web/tests?filter=advanced_ui`
while logged in as an administrator.

## DataTable

A table with the layouts and behaviours of the list demo: striped, bordered, headless,
fixed layout, row selection, sorting, a row menu, a scrollable area with a sticky
header, infinite loading, resizable columns, keyboard navigation between cells, and
header filters.

### Enabling it

```js
import { DataTable } from "@advanced_ui/datatable/datatable";
```

Declare it in a component and render it in its template:

```js
export class MyList extends Component {
    static template = "my_module.MyList";
    static components = { DataTable };
    setup() {
        this.columns = [
            { key: "name", label: "Name", type: "link", sortable: true },
            { key: "amount", label: "Amount", type: "number", sortable: true },
        ];
        this.rows = [{ id: 1, name: "Acme", amount: 25000 }];
    }
}
```

```xml
<DataTable columns="this.columns" rows="this.rows" selection="'multi'"/>
```

Props that are expressions in the template need quotes for strings: `sortKey="'name'"`.
Booleans are written as `true`.

### Props

| Prop | Description |
|---|---|
| `columns` | Column definitions, see below |
| `rows` | `[{ id, ...values }]`. Each row needs a unique `id` |
| `sortKey`, `sortDirection` | Initial sort (`"asc"` or `"desc"`) |
| `striped`, `bordered`, `headless`, `fixedLayout`, `noRowHover` | Layout switches |
| `selection` | `"none"` (default), `"multi"` (checkboxes) or `"single"` (radio buttons) |
| `onSelectionChange(ids)` | Called when the selection changes |
| `resizable` | Columns can be resized by dragging their header edge |
| `keyboard` | Arrow keys move between cells (default `true`) |
| `scrollable`, `maxHeight` | Rows scroll in an area of this height, with a sticky header |
| `rowActions` | `[{ label, onSelect(row) }]`, shown in a menu on each row |
| `onLoadMore()` | Called when a scrollable table reaches its bottom. Returns a promise |
| `filters`, `onFilterChange(key, value)` | Header filter values, and the callback when they change |

### Columns

| Key | Description |
|---|---|
| `key` | Field name in the row. Required |
| `label` | Header text |
| `type` | `"text"` (default), `"number"`, `"date"` (ISO string), `"link"`, `"email"`, or `"field"` |
| `sortable` | Clicking the header sorts the rows |
| `fixed` | The column cannot be resized |
| `format(value, row)` | Text shown in the cell |
| `filter` | Filter type, see below |
| `selection` | `[[value, label]]`, options of a `selection` filter |
| `searchRecords(term, { offset, limit })` | Search of a `relation` filter, see below |

`type: "field"` renders the Odoo field widget of each record, so the rows must be
records of a model. Such columns are not sortable.

### Custom cells

A `cell` slot replaces the content of each cell, for everything except `type: "field"`:

```xml
<DataTable columns="this.columns" rows="this.rows">
    <t t-set-slot="cell" t-slot-scope="scope">
        <span t-if="scope.column.key === 'stage'" class="badge text-bg-info" t-out="scope.value"/>
        <span t-else="" t-out="scope.text"/>
    </t>
</DataTable>
```

The slot receives `row`, `column`, `value` (the raw value) and `text` (the formatted value).

### Header filters

A column with `filter` shows a ▼ button in its header. It opens a popover with the
controls of that type. The popover has Apply and Clear buttons. Apply sends the value to
`onFilterChange(key, value)`, and Clear sends the empty value. DataTable does not filter
the rows itself: the parent turns the filter values into a domain, so the filter also
works when the rows come from the server.

| `filter` | Popover | Value | Domain |
|---|---|---|---|
| `"text"` | Operator (Contains, Equals, Does not contain) and a text input | `{ operator, value }` | `[key, operator, value]` |
| `"selection"` | Search, select all, and a checkbox per option | array of values | `[key, "in", values]` |
| `"bool"` | Same as selection, with Yes and No | array of booleans | `[key, "in", values]` |
| `"date"`, `"datetime"` | Operator (Between, Equals, Before, After) and one or two dates | `{ operator, from, to }` | `>=`, `<=` on the bounds, or `=`, `<`, `>` |
| `"number"` | Min and max inputs | `{ min, max }` | `>=`, `<=` |
| `"relation"` | Search, and a checkbox per record, 20 per page with a pager | array of `{ id, name }` | `[key, "in", ids]` |

For `"datetime"` the bounds are the start and the end of the days in the user's timezone,
converted to UTC. The domain helpers are in `static/src/datatable/filter_domain.js`:

```js
import { buildFilterDomain } from "@advanced_ui/datatable/filter_domain";

const domain = buildFilterDomain(this.columns, this.state.filters);
```

Conditions are combined with AND. Empty values add no condition.

The search function of a `relation` column returns one page and the total number of matches:

```js
async searchRecords(term, { offset, limit }) {
    const records = await orm.call("res.partner", "name_search", [], {...});
    return { records: [{ id, name }, ...], count: total };
}
```

The popover shows 20 options per page. Choosing or searching does not reset the checked
records, so they stay selected while the user pages or searches.

### Paging with a filter

The parent keeps the page (`offset`, `limit`) and the filters. When the filters change, it
resets `offset` to 0. The total of the `Pager` is the number of rows that match the
filters, so paging and filtering work together:

```xml
<Pager offset="this.state.offset" limit="this.state.limit" total="this.filteredRows.length"
    onUpdate="(params) => this.onUpdate(params)"/>
<DataTable columns="this.columns" rows="this.pageRows" filters="this.state.filters"
    onFilterChange="(key, value) => this.onFilterChange(key, value)"/>
```

### Demo and tests

The demo is in the Technical menu, under Data Table (`advanced_ui.datatable_demo`). It
shows every layout, the paging, the custom cells, the header filters, and the relation
filter. The demo filters the rows in JavaScript with `matchesDomain` from `filter_domain.js`.

The tests are in `static/tests/datatable.test.js`. Run them in the browser as described in
the Tests section above, with the filter `datatable:`.
