import { Component, proxy, t, useProps } from "@odoo/owl";

/**
 * Accordion: a list of collapsible sections. Each item has a summary (always visible)
 * and details (visible when the item is open).
 *
 * Props:
 * - items: [{ id, summary, details }], details can be a string or a template
 * - multiple: whether several items can be open at the same time (default: one at a time)
 * - openIds: ids of the items open at the start
 */
export class Accordion extends Component {
    static template = "advanced_ui.Accordion";
    props = useProps({
        items: t.array(),
        multiple: t.boolean().optional(),
        openIds: t.array().optional(),
    });

    setup() {
        this.state = proxy({ openIds: [...(this.props.openIds || [])] });
    }

    isOpen(item) {
        return this.state.openIds.includes(item.id);
    }

    toggle(item) {
        if (this.isOpen(item)) {
            this.state.openIds = this.state.openIds.filter((id) => id !== item.id);
        } else if (this.props.multiple) {
            this.state.openIds = [...this.state.openIds, item.id];
        } else {
            this.state.openIds = [item.id];
        }
    }

    onSummaryKeydown(ev, item) {
        if (ev.key === "Enter" || ev.key === " ") {
            ev.preventDefault();
            this.toggle(item);
        }
    }
}
