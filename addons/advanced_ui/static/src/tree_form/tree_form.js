import { Component, onWillStart, onWillUpdateProps, proxy, t, useProps } from "@odoo/owl";
import { registry } from "@web/core/framework/registry";
import { useService } from "@web/core/utils/hooks";
import { standardActionServiceProps } from "@web/webclient/actions/action_plugin";
import { View } from "@web/views/view";

/**
 * Tree form: a hierarchical model on the left, and on the right the form of the
 * selected record. The form is a regular Odoo form view, so its fields and groups
 * are configured in the form arch.
 *
 * The action is configured with its params:
 *  - res_model: the hierarchical model (required)
 *  - parent_field: the parent field of the model (default "parent_id")
 *  - label_field: the field shown as the label of each node (default "display_name")
 *  - limit: the number of nodes loaded at once (default 200)
 *  - form_view_id: the id of the form view on the right (default: the default form)
 */

const DEFAULT_LIMIT = 200;

export class TreeNav extends Component {
    static template = "advanced_ui.TreeNav";
    props = useProps({
        resModel: t.string(),
        parentField: t.string(),
        labelField: t.string(),
        limit: t.number().optional(),
        context: t.object().optional(),
        selectedId: t.or([t.number(), t.literal(false)]).optional(),
        reloadKey: t.number().optional(),
        onSelect: t.function(),
    });

    setup() {
        this.orm = useService("orm");
        this.state = proxy({ nodes: new Map(), roots: [], expanded: new Set(), limit: 0, hasMore: false, loading: true });
        onWillStart(() => this.load(true));
        onWillUpdateProps((nextProps) => {
            if (nextProps.resModel !== this.props.resModel || nextProps.reloadKey !== this.props.reloadKey) {
                return this.load(true);
            }
        });
    }

    get pageSize() {
        return this.props.limit || DEFAULT_LIMIT;
    }

    /** The visible rows of the tree, depth first, following the expanded nodes. */
    get rows() {
        const rows = [];
        const visit = (id, depth) => {
            const node = this.state.nodes.get(id);
            rows.push({ node, depth });
            if (this.state.expanded.has(id)) {
                for (const childId of node.childIds) {
                    visit(childId, depth + 1);
                }
            }
        };
        for (const rootId of this.state.roots) {
            visit(rootId, 0);
        }
        return rows;
    }

    /**
     * Reads one page of nodes: `limit + 1` records are read, the extra one tells
     * whether there is a next page.
     *
     * @param {boolean} reset whether the tree starts again from the first page
     */
    async load(reset = false) {
        if (reset) {
            this.state.limit = this.pageSize;
        }
        const { resModel, parentField, labelField, context } = this.props;
        const fields = [...new Set(["id", labelField, parentField])];
        const records = await this.orm.searchRead(resModel, [], fields, {
            context,
            limit: this.state.limit + 1,
        });
        this.state.hasMore = records.length > this.state.limit;
        this.buildTree(records.slice(0, this.state.limit), labelField, parentField);
        this.state.loading = false;
    }

    buildTree(records, labelField, parentField) {
        const nodes = new Map();
        for (const record of records) {
            const parentValue = record[parentField];
            nodes.set(record.id, {
                id: record.id,
                label: String(record[labelField] || record.display_name || record.id),
                parentId: (Array.isArray(parentValue) ? parentValue[0] : parentValue) || false,
                childIds: [],
            });
        }
        const roots = [];
        for (const node of nodes.values()) {
            if (node.parentId && nodes.has(node.parentId)) {
                nodes.get(node.parentId).childIds.push(node.id);
            } else {
                roots.push(node.id);
            }
        }
        this.state.nodes = nodes;
        this.state.roots = roots;
        // The first level is open, so that the nodes under the roots are visible
        this.state.expanded = new Set(roots);
    }

    onLoadMore() {
        this.state.limit += this.pageSize;
        return this.load();
    }

    toggle(nodeId) {
        if (this.state.expanded.has(nodeId)) {
            this.state.expanded.delete(nodeId);
        } else {
            this.state.expanded.add(nodeId);
        }
    }

    onToggle(ev, nodeId) {
        ev.stopPropagation();
        this.toggle(nodeId);
    }

    onSelect(nodeId) {
        this.props.onSelect(nodeId);
    }
}

export class TreeFormAction extends Component {
    static template = "advanced_ui.TreeFormAction";
    static components = { TreeNav, View };
    props = useProps({ ...standardActionServiceProps });

    setup() {
        this.orm = useService("orm");
        this.state = proxy({ selectedId: false, creating: false, sidebarOpen: true, reloadKey: 0 });
    }

    /** The buttons of the toolbar: each calls a method on the selected record. */
    get toolbarButtons() {
        return this.params.toolbar_buttons || [];
    }

    /**
     * Calls the method of a toolbar button on the selected record, then reads the
     * tree again, since the method may have changed it.
     *
     * @param {{ label: string, method: string }} button
     */
    async onToolbarButton(button) {
        if (!this.state.selectedId) {
            return;
        }
        await this.orm.call(this.params.res_model, button.method, [[this.state.selectedId]], {
            context: this.props.action.context || {},
        });
        this.onRefresh();
    }

    get title() {
        return this.props.action.name || "";
    }

    toggleSidebar() {
        this.state.sidebarOpen = !this.state.sidebarOpen;
    }

    /** Opens an empty form on the right, to create a record. */
    onNew() {
        this.state.creating = true;
        this.state.selectedId = false;
    }

    /** Reads the tree again. */
    onRefresh() {
        this.state.reloadKey++;
    }

    get showForm() {
        return this.state.creating || Boolean(this.state.selectedId);
    }

    get params() {
        return this.props.action.params || {};
    }

    get treeProps() {
        const { res_model: resModel, parent_field, label_field, limit } = this.params;
        return {
            resModel,
            parentField: parent_field || "parent_id",
            labelField: label_field || "display_name",
            limit: limit || DEFAULT_LIMIT,
            context: this.props.action.context || {},
            selectedId: this.state.selectedId,
            reloadKey: this.state.reloadKey,
            onSelect: (id) => {
                this.state.creating = false;
                this.state.selectedId = id;
            },
        };
    }

    get viewProps() {
        return {
            type: "form",
            resModel: this.params.res_model,
            resId: this.state.creating ? false : this.state.selectedId,
            viewId: this.params.form_view_id || false,
            context: this.props.action.context || {},
            display: { controlPanel: false },
        };
    }
}

registry.category("actions").add("advanced_ui.tree_form", TreeFormAction);
