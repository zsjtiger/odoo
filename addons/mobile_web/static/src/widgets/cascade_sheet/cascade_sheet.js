import { Component, onWillStart, proxy, t, useProps, xml } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { fieldTexts } from "@mobile_web/core/texts";

/**
 * 级联选择的底部弹层(省 > 市 > 区), 按层级模型的 parent_id 逐级选择.
 *
 * - 顶部标签是已进入的层级路径, 点击标签返回对应层级
 * - 列表是当前层级的选项, 有下级的选项带 "›", 点击后进入下一级
 * - 点击任一选项即选中它(包括有下级的), 确认后交回选中项
 *
 * props.relation: 层级模型(需要 parent_id 与 child_ids 字段)
 * props.selected: 当前值 [{id, name}] 或 []
 */
export class MobileCascadeSheet extends Component {
    texts = fieldTexts;
    static template = xml`
        <t t-name="mobile_web.MobileCascadeSheet">
            <div class="m_sheet_backdrop" t-on-click="this.onBackdropClick">
                <div class="m_sheet m_cascade_sheet" role="dialog">
                    <header class="m_sheet_header">
                        <button type="button" class="m_sheet_btn" t-on-click="this.onCancel"><t t-esc="this.texts.cancel"/></button>
                        <span class="m_sheet_title"><t t-esc="this.props.title"/></span>
                        <button type="button" class="m_sheet_btn m_sheet_btn_primary" t-on-click="this.onConfirm"><t t-esc="this.texts.confirm"/></button>
                    </header>
                    <div class="m_cascade_tabs" role="tablist">
                        <button t-foreach="this.tabs" t-as="tab" t-key="tab.level" type="button" role="tab"
                                t-attf-class="m_cascade_tab {{ tab.active ? 'is_active' : '' }}"
                                t-att-data-level="tab.level" t-on-click="this.onTabClick">
                            <t t-esc="tab.name"/>
                        </button>
                    </div>
                    <ul class="m_sheet_list">
                        <t t-foreach="this.state.items" t-as="item" t-key="item.id">
                            <li>
                                <button type="button" t-attf-class="m_sheet_item {{ this.isSelected(item) ? 'is_selected' : '' }}"
                                        t-att-data-index="item_index" t-on-click="this.onItemClick">
                                    <span class="m_sheet_item_name"><t t-esc="item.name"/></span>
                                    <span t-if="this.isSelected(item)" class="m_sheet_check">✓</span>
                                    <span t-elif="item.hasChildren" class="m_cascade_more">›</span>
                                </button>
                            </li>
                        </t>
                        <li t-if="this.state.loading" class="m_sheet_status"><t t-esc="this.texts.loading"/></li>
                        <li t-elif="!this.state.items.length" class="m_sheet_status"><t t-esc="this.texts.noMatch"/></li>
                    </ul>
                </div>
            </div>
        </t>
    `;
    props = useProps({
        title: t.string().optional(""),
        relation: t.string(),
        selected: t.array().optional([]),
        onConfirm: t.function(),
        onClose: t.function(),
    });
    orm = useService("orm");

    state = proxy({
        // 已进入的层级路径(从顶层到当前层级), 空表示顶层
        path: [],
        items: [],
        selected: null,
        loading: false,
    });

    setup() {
        onWillStart(async () => {
            const current = this.props.selected[0] || null;
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
        const tabs = [{ level: 0, name: this.texts.select, active: path.length === 0 }];
        path.forEach((node, index) => {
            tabs.push({ level: index + 1, name: node.name, active: index === path.length - 1 });
        });
        return tabs;
    }

    isSelected(item) {
        return Boolean(this.state.selected) && this.state.selected.id === item.id;
    }

    async onItemClick(ev) {
        const item = this.state.items[Number(ev.currentTarget.dataset.index)];
        if (!item) {
            return;
        }
        // 选中项的名称与服务端的显示名称一致: 完整路径, 例如 "北京市 北京市 东城区"
        const fullName = [...this.state.path.map((node) => node.name), item.name].join(" ");
        this.state.selected = { id: item.id, name: fullName };
        if (item.hasChildren) {
            this.state.path = [...this.state.path, item];
            await this.loadChildren(item.id);
        }
    }

    async onTabClick(ev) {
        const level = Number(ev.currentTarget.dataset.level);
        if (level >= this.state.path.length) {
            return;
        }
        this.state.path = this.state.path.slice(0, level);
        await this.loadChildren(level ? this.state.path[level - 1].id : false);
    }

    onConfirm() {
        this.props.onConfirm(this.state.selected ? [this.state.selected] : []);
    }

    onCancel() {
        this.props.onClose();
    }

    onBackdropClick(ev) {
        if (ev.target.classList.contains("m_sheet_backdrop")) {
            this.props.onClose();
        }
    }
}
