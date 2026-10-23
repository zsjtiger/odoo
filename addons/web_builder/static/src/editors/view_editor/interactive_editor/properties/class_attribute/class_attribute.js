import { Component, t, useProps } from "@odoo/owl";
import { _t } from "@web/core/data/l10n/translation";
import { Property } from "@web_builder/editors/view_editor/property/property";

export class ClassAttribute extends Component {
    static template = "web_builder.ViewEditor.ClassAttribute";
    static components = {
        Property,
    };
    props = useProps({
        value: t.string().optional(),
        onChange: t.function(),
    });
    get tooltip() {
        return _t(
            "Use Bootstrap or any other custom classes to customize the style and the display of the element."
        );
    }
}
