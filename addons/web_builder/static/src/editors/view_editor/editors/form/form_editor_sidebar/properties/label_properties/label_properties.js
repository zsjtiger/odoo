import { Component, t, useProps } from "@odoo/owl";
import { Property } from "@web_builder/editors/view_editor/property/property";
import { SidebarPropertiesToolbox } from "@web_builder/editors/view_editor/interactive_editor/properties/sidebar_properties_toolbox/sidebar_properties_toolbox";
import { useEditNodeAttributes } from "@web_builder/editors/view_editor/view_editor_model";

export class LabelProperties extends Component {
    static template = "web_builder.ViewEditor.InteractiveEditorProperties.Label";
    static components = { Property, SidebarPropertiesToolbox };

    props = useProps({
        node: t.object(),
    });

    setup() {
        this.editNodeAttributes = useEditNodeAttributes();
    }

    onChangeAttribute(value, name) {
        return this.editNodeAttributes({ [name]: value });
    }
}
