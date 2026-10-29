import { useLayoutEffect } from "@web/core/owl/utils";
import { CharField, charField } from "@web/views/fields/text/char/char_field";
import { registry } from "@web/core/framework/registry";

class DescriptionPageField extends CharField {
    static template = "survey.DescriptionPageField";
    setup() {
        super.setup();
        useLayoutEffect(
            (input) => {
                if (input) {
                    input.classList.add("col");
                }
            },
            () => [this.input()]
        );
    }
    onExternalBtnClick() {
        this.env.openRecord(this.props.record);
    }
}

registry.category("fields").add("survey_description_page", {
    ...charField,
    component: DescriptionPageField,
});
