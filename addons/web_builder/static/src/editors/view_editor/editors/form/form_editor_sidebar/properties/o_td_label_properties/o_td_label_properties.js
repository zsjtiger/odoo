import { Component } from "@odoo/owl";
import { SidebarPropertiesToolbox } from "@web_builder/editors/view_editor/interactive_editor/properties/sidebar_properties_toolbox/sidebar_properties_toolbox";

export class OTdLabelProperties extends Component {
    static template = "web_builder.ViewEditor.InteractiveEditorProperties.OTdLabelProperties";
    static components = { SidebarPropertiesToolbox };
}
