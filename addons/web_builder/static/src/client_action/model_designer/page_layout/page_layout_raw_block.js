import { Component, proxy, t, useProps } from "@odoo/owl";

/** An advanced block of a page layout: shown, and editable as XML. */
export class RawBlock extends Component {
    static template = "web_builder.PageLayoutRawBlock";

    props = useProps({
        block: t.object(),
        editor: t.object(),
    });
}
