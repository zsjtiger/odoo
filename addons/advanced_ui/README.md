# Advanced UI

Advanced controls for the Odoo web client. The addon currently provides the
**Accordion** control.

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
import { Component, useState } from "@odoo/owl";
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
component template. Passing records and field definitions to `<Field>` or a list
renderer is up to the component that owns the data. A field widget that does this
automatically from a form view is not provided yet.

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

The fields in a row are read-only in the current version. Nested One2many or list
views inside a row are not supported yet.

### Lookup dropdown for many2one

The `lookup` widget is an opt-in dropdown for many2one fields. Its suggestions are
drawn as rows: a coloured tile with the record's initial, the name, and a subtitle
taken from a field of the related model. The default many2one dropdown is unchanged.

```xml
<field name="partner_id" widget="lookup" options="{'subtitle': 'city'}"/>
```

- `options="{'subtitle': 'city'}"` names a char field of the related model shown under
  each name. Without it, the subtitle is empty.
- The tile colour is chosen from the record id, so it does not follow the model.
- Section headers (such as "Accounts" and "Opportunities", one per model) are not
  supported yet: the lookup shows the results of the field's own model only.

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

### Tests

The unit tests live in `static/tests/accordion.test.js`. They are JavaScript (Hoot)
tests, run in the browser: install or update the addon on a database, then open
`/web/tests?filter=advanced_ui` while logged in as an administrator.
