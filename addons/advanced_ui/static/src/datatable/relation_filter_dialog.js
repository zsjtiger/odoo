import { Component, onWillStart, proxy, t, useProps } from "@odoo/owl";
import { Dialog } from "@web/core/dialogs/dialog/dialog";

/**
 * Dialog to pick the records of a relational filter: search, check the records,
 * then confirm. The parent gives `searchRecords(term)`, which resolves to [{ id, name }].
 */
export class RelationFilterDialog extends Component {
    static template = "advanced_ui.RelationFilterDialog";
    static components = { Dialog };
    props = useProps({
        title: t.string().optional(),
        searchRecords: t.function(),
        selected: t.array(),
        onConfirm: t.function(),
        close: t.function(),
    });

    setup() {
        this.state = proxy({
            search: "",
            results: [],
            selected: [...this.props.selected],
        });
        onWillStart(() => this.search(""));
    }

    async search(term) {
        this.state.search = term;
        this.state.results = await this.props.searchRecords(term);
    }

    isSelected(record) {
        return this.state.selected.some((selected) => selected.id === record.id);
    }

    toggle(record) {
        if (this.isSelected(record)) {
            this.state.selected = this.state.selected.filter((selected) => selected.id !== record.id);
        } else {
            this.state.selected.push({ id: record.id, name: record.name });
        }
    }

    confirm() {
        this.props.onConfirm([...this.state.selected]);
        this.props.close();
    }
}
