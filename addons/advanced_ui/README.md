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
