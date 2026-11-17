import { Component, t, useProps } from "@odoo/owl";
import { Property } from "@web_builder/editors/view_editor/property/property";
import { ClassAttribute } from "@web_builder/editors/view_editor/interactive_editor/properties/class_attribute/class_attribute";
import { ViewStructureProperties } from "@web_builder/editors/view_editor/interactive_editor/properties/view_structure_properties/view_structure_properties";
import { useEditNodeAttributes } from "@web_builder/editors/view_editor/view_editor_model";

export class FooterProperties extends Component {
    static template = "web_builder.ViewEditor.InteractiveEditorProperties.Footer";
    static components = {
        ClassAttribute,
        Property,
        ViewStructureProperties,
    };
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
