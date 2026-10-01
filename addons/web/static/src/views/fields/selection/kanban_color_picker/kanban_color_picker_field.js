import { _t } from "@web/core/data/l10n/translation";
import { ColorList } from "@web/core/components/colorlist/colorlist";
import { registry } from "@web/core/framework/registry";
import { standardFieldProps } from "../../standard_field_props";

import { Component, useProps } from "@odoo/owl";

class KanbanColorPickerField extends Component {
    static template = "web.KanbanColorPickerField";
    props = useProps(standardFieldProps);

    get colors() {
        return ColorList.COLORS;
    }

    selectColor(colorIndex) {
        return this.props.record.update({ [this.props.name]: colorIndex }, { save: true });
    }
}

export const kanbanColorPickerField = {
    component: KanbanColorPickerField,
    displayName: _t("Color Picker"),
    extractProps(fieldInfo, dynamicInfo) {
        return {
            readonly: dynamicInfo.readonly,
        };
    },
};

registry.category("fields").add("kanban_color_picker", kanbanColorPickerField);
