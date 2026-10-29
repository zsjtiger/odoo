import { _t } from "@web/core/data/l10n/translation";

/** Friendly names of the field types, the way Salesforce names them. */
export function getFieldTypeLabels() {
    return {
        boolean: _t("Checkbox"),
        char: _t("Text"),
        text: _t("Long text"),
        html: _t("Rich text"),
        integer: _t("Number"),
        float: _t("Decimal"),
        monetary: _t("Currency"),
        date: _t("Date"),
        datetime: _t("Date/Time"),
        selection: _t("Picklist"),
        many2one: _t("Lookup"),
        many2many: _t("Multi-select lookup"),
        one2many: _t("Related list"),
        binary: _t("File"),
        image: _t("Image"),
        properties: _t("Properties"),
    };
}
