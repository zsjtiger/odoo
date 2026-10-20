import { Component, proxy } from "@odoo/owl";
import { registry } from "@web/core/framework/registry";
import { ExpressionBuilder } from "./expression_builder";
import { defaultTree } from "./expression_logic";

const FIELDS = [
    { name: "name", label: "Name", kind: "char" },
    { name: "amount", label: "Amount", kind: "number" },
    { name: "close_date", label: "Close Date", kind: "date" },
    { name: "won", label: "Won", kind: "boolean" },
    {
        name: "stage",
        label: "Stage",
        kind: "selection",
        choices: [
            ["new", "New"],
            ["won", "Won"],
            ["lost", "Lost"],
        ],
    },
];

export class ExpressionBuilderDemo extends Component {
    static template = "advanced_ui.ExpressionBuilderDemo";
    static components = { ExpressionBuilder };

    fields = FIELDS;

    setup() {
        this.state = proxy({ tree: defaultTree() });
    }

    onTreeChange(tree) {
        this.state.tree = tree;
    }
}

registry.category("actions").add("advanced_ui.expression_builder_demo", ExpressionBuilderDemo);
