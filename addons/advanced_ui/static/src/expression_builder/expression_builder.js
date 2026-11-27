import { Component, proxy, t, useEffect, useProps } from "@odoo/owl";
import { _t } from "@web/core/data/l10n/translation";
import { registry } from "@web/core/framework/registry";
import { standardFieldProps } from "@web/views/fields/standard_field_props";
import {
    MODES,
    OPERATORS,
    defaultTree,
    fieldKind,
    newCondition,
    newGroup,
    toDomain,
} from "./expression_logic";

const CONNECTORS = { all: _t("AND"), any: _t("OR") };

function cloneTree(tree) {
    return JSON.parse(JSON.stringify(tree));
}

/**
 * A group of conditions, with its own mode. Groups nest: a child group is
 * rendered by the same component. All changes go to the tree object, then
 * `onChange` tells the root to report the new tree.
 */
export class ExpressionGroup extends Component {
    static template = "advanced_ui.ExpressionGroup";
    static components = { ExpressionGroup };

    props = useProps({
        node: t.object(),
        fields: t.array(),
        readonly: t.boolean().optional(),
        depth: t.number().optional(),
        onChange: t.function(),
        onRemove: t.function().optional(),
    });

    modes = MODES;
    connectors = CONNECTORS;

    get customError() {
        if (this.props.node.mode !== "custom") {
            return "";
        }
        try {
            toDomain(this.props.node);
            return "";
        } catch (error) {
            return error.message;
        }
    }

    fieldOf(condition) {
        return this.props.fields.find((field) => field.name === condition.resource);
    }

    operatorsOf(condition) {
        return OPERATORS[this.fieldOf(condition)?.kind ?? "char"];
    }

    isValueNeeded(condition) {
        const operator = this.operatorsOf(condition).find((op) => op.value === condition.operator);
        return !operator?.noValue;
    }

    get hasConditions() {
        return this.props.node.children.some((child) => child.kind === "condition");
    }

    onModeChange(ev) {
        this.props.node.mode = ev.target.value;
        this.props.onChange();
    }

    onCustomLogicChange(ev) {
        this.props.node.customLogic = ev.target.value;
        this.props.onChange();
    }

    onFormulaChange(ev) {
        this.props.node.formula = ev.target.value;
        this.props.onChange();
    }

    onResourceChange(condition, ev) {
        const field = this.props.fields.find((f) => f.name === ev.target.value);
        condition.resource = field?.name ?? "";
        condition.type = field?.kind ?? "";
        condition.operator = this.operatorsOf(condition)[0].value;
        condition.value = "";
        this.props.onChange();
    }

    onOperatorChange(condition, ev) {
        condition.operator = ev.target.value;
        if (!this.isValueNeeded(condition)) {
            condition.value = "";
        }
        this.props.onChange();
    }

    onValueChange(condition, ev) {
        condition.value = ev.target.value;
        this.props.onChange();
    }

    onAddCondition() {
        this.props.node.children.push(newCondition());
        this.props.onChange();
    }

    onAddGroup() {
        this.props.node.children.push(newGroup("all"));
        this.props.onChange();
    }

    onRemoveChild(index) {
        this.props.node.children.splice(index, 1);
        this.props.onChange();
    }
}

/**
 * Expression builder: builds a logical expression over the fields of a model.
 * The value is a tree (see expression_logic.js); `onChange` receives the new tree.
 *
 * <ExpressionBuilder fields="fields" value="tree" onChange="onTreeChange"/>
 */
export class ExpressionBuilder extends Component {
    static template = "advanced_ui.ExpressionBuilder";
    static components = { ExpressionGroup };

    props = useProps({
        fields: t.array(),
        value: t.object().optional(),
        readonly: t.boolean().optional(),
        onChange: t.function().optional(),
    });

    setup() {
        this.state = proxy({
            tree: this.props.value ? cloneTree(this.props.value) : defaultTree(),
        });
        this.notify = this.notify.bind(this);
        // Takes over a value changed from outside, unless it is what the builder shows
        useEffect(
            (serialized) => {
                if (serialized && serialized !== JSON.stringify(this.state.tree)) {
                    this.state.tree = JSON.parse(serialized);
                }
            },
            () => [this.props.value ? JSON.stringify(this.props.value) : null]
        );
    }

    notify() {
        this.props.onChange?.(cloneTree(this.state.tree));
    }
}

/**
 * Field widget storing the expression tree as JSON in a char field. The
 * resources are the fields of the model that the builder can compare.
 *
 * <field name="expression" widget="expression_builder"/>
 */
export class ExpressionBuilderField extends Component {
    static template = "advanced_ui.ExpressionBuilderField";
    static components = { ExpressionBuilder };

    props = useProps({ ...standardFieldProps });

    get fields() {
        return Object.values(this.props.record.fields)
            .map((field) => ({
                name: field.name,
                label: field.string,
                kind: fieldKind(field.type),
                choices: field.selection ?? [],
            }))
            .filter((field) => field.kind)
            .sort((a, b) => a.label.localeCompare(b.label));
    }

    get tree() {
        const serialized = this.props.record.data[this.props.name];
        return serialized ? JSON.parse(serialized) : undefined;
    }

    onChange(tree) {
        this.props.record.update({ [this.props.name]: JSON.stringify(tree) });
    }
}

registry.category("fields").add("expression_builder", {
    component: ExpressionBuilderField,
    displayName: _t("Expression Builder"),
    supportedTypes: ["char", "text"],
});
