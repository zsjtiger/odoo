import { Component, proxy } from "@odoo/owl";
import { registry } from "@web/core/framework/registry";
import { TimePicker } from "./timepicker";

export class TimePickerDemo extends Component {
    static template = "advanced_ui.TimePickerDemo";
    static components = { TimePicker };

    setup() {
        this.state = proxy({ start: "09:30", end: "", quarter: "10:15" });
    }

    setValue(key, time) {
        this.state[key] = time;
    }
}

registry.category("actions").add("advanced_ui.timepicker_demo", TimePickerDemo);
