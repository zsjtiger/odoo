import { Component, onWillStart, proxy, t, useProps, xml } from "@odoo/owl";
import { Dialog } from "@web/core/dialogs/dialog/dialog";
import { registry } from "@web/core/framework/registry";
import { useService } from "@web/core/utils/hooks";
import { standardFieldProps } from "@web/views/fields/standard_field_props";

/**
 * 级联选择弹窗(省 > 市 > 区): 按层级模型的 parent_id 逐级选择, 与移动端的级联选择一致.
 * 顶部标签是已进入的层级路径, 列表是当前层级的选项; 点击有下级的选项进入下一级并选中它, 确认后交回选中项.
 *
 * props.relation: 层级模型(需要 parent_id 与 child_ids 字段)
 * props.selected: 当前值 [{id, name}] 或 []
 */
export class CascadeDialog extends Component {
    static components = { Dialog };
    props = useProps({
        title: t.string().optional(""),
        relation: t.string(),
        selected: t.array().optional([]),
        onConfirm: t.function(),
        close: t.function(),
    });
    static template = xml`
        <Dialog title="this.props.title" size="'md'">
            <div class="o_cascade_tabs d-flex gap-1 overflow-auto border-bottom pb-1 mb-2" role="tablist">
                <t t-foreach="this.tabs" t-as="tab" t-key="tab.level">
                    <button type="button" role="tab" class="btn btn-link text-nowrap"
                            t-att-class="tab.active ? 'fw-bold text-primary' : 'text-muted'"
                            t-on-click="() => this.onTab(tab.level)">
                        <t t-esc="tab.name"/>
                    </button>
                </t>
            </div>
            <div class="list-group">
                <t t-foreach="this.state.items" t-as="item" t-key="item.id">
                    <button type="button" class="list-group-item list-group-item-action d-flex justify-content-between align-items-center"
                            t-att-class="this.isSelected(item) ? 'active' : ''" t-on-click="() => this.onItem(item)">
                        <span t-esc="item.name"/>
                        <span t-if="this.isSelected(item)">✓</span>
                        <span t-elif="item.hasChildren">›</span>
                    </button>
                </t>
                <div t-if="this.state.loading" class="list-group-item text-muted">Loading…</div>
                <div t-elif="!this.state.items.length" class="list-group-item text-muted">No records</div>
            </div>
            <t t-set-slot="footer">
                <button type="button" class="btn btn-secondary" t-on-click="() => this.props.close()">Cancel</button>
                <button type="button" class="btn btn-primary" t-on-click="this.onConfirm">Confirm</button>
            </t>
        </Dialog>
    `;

    orm = useService("orm");
    state = proxy({ path: [], items: [], selected: null, loading: false });

    setup() {
        onWillStart(async () => {
            const current = this.props.selected?.[0] || null;
            this.state.selected = current;
            // 打开时停留在当前值所在的层级, 列表中可以看到同级的选项
            let parentId = current ? await this.parentOf(current.id) : false;
            const path = [];
            while (parentId) {
                const [node] = await this.orm.read(this.props.relation, [parentId], ["name", "parent_id"]);
                path.unshift({ id: node.id, name: node.name });
                parentId = node.parent_id ? node.parent_id[0] : false;
            }
            this.state.path = path;
            await this.loadChildren(path.length ? path[path.length - 1].id : false);
        });
    }

    async parentOf(id) {
        const [node] = await this.orm.read(this.props.relation, [id], ["parent_id"]);
        return node && node.parent_id ? node.parent_id[0] : false;
    }

    /** 读取某个层级(parentId 为 false 时是顶层)下的选项 */
    async loadChildren(parentId) {
        this.state.loading = true;
        try {
            const records = await this.orm.searchRead(
                this.props.relation,
                [["parent_id", "=", parentId]],
                ["name", "child_ids"]
            );
            this.state.items = records.map((r) => ({
                id: r.id,
                name: r.name,
                hasChildren: Boolean(r.child_ids && r.child_ids.length),
            }));
        } finally {
            this.state.loading = false;
        }
    }

    /** 标签: 第 0 个是顶层(占位), 之后每个是一级已进入的层级 */
    get tabs() {
        const path = this.state.path;
        const tabs = [{ level: 0, name: "Select…", active: path.length === 0 }];
        path.forEach((node, index) => {
            tabs.push({ level: index + 1, name: node.name, active: index === path.length - 1 });
        });
        return tabs;
    }

    isSelected(item) {
        return Boolean(this.state.selected) && this.state.selected.id === item.id;
    }

    async onItem(item) {
        // 选中项的名称与服务端的显示名称一致: 完整路径
        const fullName = [...this.state.path.map((node) => node.name), item.name].join(" ");
        this.state.selected = { id: item.id, name: fullName };
        if (item.hasChildren) {
            this.state.path = [...this.state.path, item];
            await this.loadChildren(item.id);
        }
    }

    async onTab(level) {
        if (level >= this.state.path.length) {
            return;
        }
        this.state.path = this.state.path.slice(0, level);
        await this.loadChildren(level ? this.state.path[level - 1].id : false);
    }

    onConfirm() {
        this.props.onConfirm(this.state.selected ? [this.state.selected] : []);
        this.props.close();
    }
}

/**
 * 级联选择 (many2one, widget="cascade"): 关联模型为层级结构(parent_id)时, 在弹窗中逐级选择.
 * 显示值为关联记录的显示名称(完整路径).
 */
export class CascadeField extends Component {
    static template = xml`
        <button type="button" class="o_input o_cascade_field text-start w-100" t-att-id="this.props.id"
                t-att-disabled="this.props.readonly" t-on-click="this.openDialog">
            <t t-if="this.displayName"><t t-esc="this.displayName"/></t>
            <span t-else="" class="text-muted">Select…</span>
        </button>
    `;
    props = useProps(standardFieldProps);

    dialog = useService("dialog");

    get value() {
        return this.props.record.data[this.props.name] || false;
    }

    get displayName() {
        return this.value ? this.value.display_name : "";
    }

    openDialog() {
        const field = this.props.record.fields[this.props.name];
        this.dialog.add(CascadeDialog, {
            title: field.string,
            relation: field.relation,
            selected: this.value ? [{ id: this.value.id, name: this.value.display_name }] : [],
            onConfirm: (selected) => {
                const item = selected[0];
                this.props.record.update({
                    [this.props.name]: item ? { id: item.id, display_name: item.name } : false,
                });
            },
        });
    }
}

registry.category("fields").add("cascade", {
    component: CascadeField,
    supportedTypes: ["many2one"],
});
