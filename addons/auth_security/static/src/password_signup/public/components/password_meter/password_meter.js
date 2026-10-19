import { Meter } from "@auth_security/password/password_meter";
import { ConcretePolicy, recommendations } from "@auth_security/password/password_policy";
import { Component, proxy, t, useListener, useProps } from "@odoo/owl";
import { registry } from "@web/core/registry";

class PasswordMeter extends Component {
    static template = "auth_security.PasswordMeter";
    static components = { Meter };

    props = useProps({
        selector: t.string(),
    });

    setup() {
        const inputEl = document.querySelector(this.props.selector);
        useListener(inputEl, "input", (e) => {
            this.state.password = e.target.value || "";
        });

        const minlength = Number(inputEl.getAttribute("minlength"));
        this.hasMinlength = !isNaN(minlength);
        this.state = proxy({
            password: inputEl.value || "",
        });
        this.required = new ConcretePolicy({ minlength });
        this.recommended = recommendations;
    }
}

registry.category("public_components").add("password_meter", PasswordMeter);
