import { Component, onWillStart, onWillUpdateProps, t, useProps, xml } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { mobileViewRegistry } from "@mobile_web/views/registries";
import { parseArch, collectFieldNames, isHiddenColumn, splitColumns } from "@mobile_web/views/arch";
import { getFieldWidget } from "@mobile_web/views/fields/index";
import { MobileRecordModel } from "@mobile_web/views/record_model";
import { RecordCollection } from "@mobile_web/views/record_list";
import { useInfiniteScroll } from "@mobile_web/views/infinite_scroll";

/**
 * 找到卡片的字段布局: 优先使用 templates 中的 card 模板, 否则使用看板根节点下的字段
 *
 * @param {import("@mobile_web/views/arch").ArchNode} root
 * @returns {import("@mobile_web/views/arch").ArchNode[]} 卡片内的节点
 */
function findCardNodes(root) {
    const templates = root.children.find((c) => c.tag === "templates");
    const card = templates && templates.children.find((c) => c.tag === "t" && c.attrs["t-name"] === "card");
    return card ? card.children : root.children;
}

/**
 * 卡片中的字段节点: 字段可能嵌套在 div / span 等容器中, 递归收集(跳过隐藏的字段)
 *
 * @param {import("@mobile_web/views/arch").ArchNode[]} nodes
 * @returns {import("@mobile_web/views/arch").ArchNode[]}
 */
function collectCardFields(nodes) {
    const fields = [];
    for (const node of nodes) {
        if (node.tag === "field" && node.attrs.name) {
            if (!isHiddenColumn(node)) {
                fields.push(node);
            }
            continue;
        }
        fields.push(...collectCardFields(node.children));
    }
    return fields;
}

/**
 * 移动端看板视图: 以卡片的形式展示记录, 标题为第一个字段, 其余字段作为卡片内容
 *
 * 只支持 arch 中的字段, 不解析 QWeb 的条件/样式指令
 */
export class MobileKanbanView extends Component {
    static template = xml`
        <t t-name="mobile_web.MobileKanbanView">
            <div class="m_kanban_view">
                <div class="m_list_meta">
                    <span t-if="this.collection.state.total !== null"><t t-esc="this.rangeText"/></span>
                    <button type="button" class="m_link_button" t-on-click="this.onRefresh">刷新</button>
                </div>
                <ul class="m_kanban">
                    <li t-foreach="this.collection.state.records" t-as="record" t-key="record.resId">
                        <button type="button" class="m_kanban_card" t-att-data-id="record.resId" t-on-click="this.onCardClick">
                            <div class="m_kanban_title" t-if="this.title">
                                <t t-component="this.getWidget(this.title)" t-props="this.cellProps(this.title, record)"/>
                            </div>
                            <div class="m_kanban_line" t-foreach="this.lines" t-as="column" t-key="column.name">
                                <t t-component="this.getWidget(column)" t-props="this.cellProps(column, record)"/>
                            </div>
                        </button>
                    </li>
                </ul>
                <p t-if="this.collection.state.error" class="m_error">加载失败, 请重试</p>
                <p t-if="!this.collection.state.loading and this.collection.state.total === 0" class="m_empty">没有记录</p>
                <div t-ref="this.infinite.sentinel" class="m_load_sentinel">
                    <t t-esc="this.sentinelText"/>
                </div>
            </div>
        </t>
    `;
    props = useProps({
        resModel: t.string(),
        arch: t.string(),
        fields: t.object(),
        domain: t.array().optional([]),
        context: t.object().optional({}),
        onSelect: t.function(),
    });
    orm = useService("orm");

    setup() {
        const root = parseArch(this.props.arch);
        const cardNodes = collectCardFields(findCardNodes(root));
        const columns = cardNodes.map((n) => ({ name: n.attrs.name, attrs: n.attrs, field: this.props.fields[n.attrs.name] }));
        const { primary, secondary } = splitColumns(columns);
        this.title = primary;
        this.lines = secondary;
        const fieldNames = [...collectFieldNames(root)];
        this.collection = new RecordCollection(
            new MobileRecordModel(this.orm, this.props.resModel, this.props.fields, this.props.context),
            fieldNames
        );
        onWillStart(() => this.collection.reload(this.props.domain));
        this.infinite = useInfiniteScroll(this.collection);
        onWillUpdateProps((nextProps) => {
            if (JSON.stringify(nextProps.domain) !== JSON.stringify(this.collection.domain)) {
                return this.collection.reload(nextProps.domain).then(() => this.infinite.recheck());
            }
        });
    }

    getWidget(column) {
        return getFieldWidget(column.attrs, column.field);
    }

    cellProps(column, record) {
        return {
            name: column.name,
            field: column.field,
            record,
            readonly: true,
            compact: true,
            attrs: column.attrs,
            onChange: () => {},
            resModel: this.props.resModel,
        };
    }

    get sentinelText() {
        const { loading, records, total } = this.collection.state;
        if (loading) {
            return "加载中…";
        }
        return total && records.length >= total ? "已显示全部" : "";
    }

    get rangeText() {
        const { records, total } = this.collection.state;
        return total ? `1-${records.length} / ${total}` : "";
    }

    onCardClick(ev) {
        this.props.onSelect(Number(ev.currentTarget.dataset.id));
    }

    onRefresh() {
        return this.collection.reload();
    }
}

mobileViewRegistry.add("kanban", MobileKanbanView);
