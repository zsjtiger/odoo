import { getFieldWidget } from "@mobile_web/views/fields/index";
import { isInvisible } from "@mobile_web/views/arch";
import { _t } from "@web/core/data/l10n/translation";

// 表单中不展示的标签: 按钮与头部操作在 v1 中不支持
const SKIPPED_TAGS = ["header", "footer", "button", "label", "field_info"];

// 这些类型的字段内容较长, 标签与内容上下排列
const STACKED_TYPES = ["text", "html", "binary"];

/**
 * 把 arch 解析为展示用的 block 树:
 *  - group: 一组字段(纵向排列)
 *  - field: 一个字段(带标签与字段组件)
 *  - notebook: 分页标签, 每页是 page
 *  - separator: 分隔标题
 *
 * @param {import("@mobile_web/views/arch").ArchNode} node
 * @param {Object} fields
 * @param {string} keyPrefix
 * @returns {Object[]}
 */
export function buildLayout(node, fields, keyPrefix = "b") {
    const blocks = [];
    node.children.forEach((child, index) => {
        const key = `${keyPrefix}.${index}`;
        if (SKIPPED_TAGS.includes(child.tag) || isInvisible(child)) {
            return;
        }
        switch (child.tag) {
            case "field": {
                const field = fields[child.attrs.name];
                if (!field) {
                    return;
                }
                blocks.push({
                    kind: "field",
                    key,
                    name: child.attrs.name,
                    attrs: child.attrs,
                    field,
                    label: child.attrs.string || field.string,
                    // 多行文本等内容较长的字段, 标签放在上方独占一行
                    stacked: STACKED_TYPES.includes(field.type),
                    widget: getFieldWidget(child.attrs, field),
                    readonly: child.attrs.readonly === "1" || child.attrs.readonly === "True" || !!field.readonly,
                });
                return;
            }
            case "notebook": {
                const pages = child.children
                    .filter((p) => p.tag === "page" && !isInvisible(p))
                    .map((page, pageIndex) => ({
                        title: page.attrs.string || _t("Page %s", pageIndex + 1),
                        blocks: buildLayout(page, fields, `${key}.${pageIndex}`),
                    }));
                blocks.push({ kind: "notebook", key, pages });
                return;
            }
            case "separator":
                blocks.push({ kind: "separator", key, text: child.attrs.string || "" });
                return;
            case "group": {
                const children = buildLayout(child, fields, key);
                if (children.length) {
                    blocks.push({ kind: "group", key, title: child.attrs.string || "", children });
                }
                return;
            }
            default: {
                // sheet / div / form 等容器: 直接展开其子节点
                const children = buildLayout(child, fields, key);
                blocks.push(...children);
            }
        }
    });
    return blocks;
}
