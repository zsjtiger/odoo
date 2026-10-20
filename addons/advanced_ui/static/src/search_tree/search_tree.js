import { patch } from "@web/core/utils/patch";
import { SearchArchParser } from "@web/search/search_arch_parser";
import { SearchModel } from "@web/search/search_model";

/**
 * Tree search panel. A `<searchpanel>` field whose related model is hierarchical
 * can name the parent field and the label field of that model:
 *
 * <searchpanel>
 *     <field name="categ_id" tree_parent="parent_id" tree_label="name"/>
 * </searchpanel>
 *
 * The values of the field are shown as a tree on the left. Selecting a node
 * filters the records on that node and on all its descendants.
 */

patch(SearchArchParser.prototype, {
    visitSearchPanel(searchPanelNode) {
        const result = super.visitSearchPanel(searchPanelNode);
        for (const node of searchPanelNode.children) {
            if (node.tagName !== "field") {
                continue;
            }
            if (!node.hasAttribute("tree_parent") && !node.hasAttribute("tree_label")) {
                continue;
            }
            const section = this.sections.find(([, s]) => s.fieldName === node.getAttribute("name"))?.[1];
            if (section?.type === "category") {
                section.tree = {
                    parent: node.getAttribute("tree_parent") || null,
                    label: node.getAttribute("tree_label") || "display_name",
                };
            }
        }
        return result;
    },
});

patch(SearchModel.prototype, {
    _createCategoryTree(sectionId, result) {
        super._createCategoryTree(sectionId, result);
        const category = this.sections.get(sectionId);
        if (!category.tree) {
            return;
        }
        if (category.tree.parent) {
            category.parentField = category.tree.parent;
        }
        this._loadTreeNodes(category);
    },

    /**
     * Reads the label and the parent of each node, so that the tree shows the
     * configured label and follows the configured parent field.
     *
     * @param {Object} category
     */
    async _loadTreeNodes(category) {
        const { label, parent } = category.tree;
        const parentName = parent || category.parentField;
        const ids = [...category.values.keys()].filter(Boolean);
        if (!ids.length) {
            return;
        }
        const loadId = (category.treeLoadId = (category.treeLoadId || 0) + 1);
        const comodel = this.searchViewFields[category.fieldName].relation;
        const fields = [...new Set([label, parentName].filter(Boolean))];
        const records = await this.orm.read(comodel, ids, fields, {
            context: this.globalContext,
        });
        if (loadId !== category.treeLoadId) {
            return;
        }
        for (const record of records) {
            const value = category.values.get(record.id);
            if (!value) {
                continue;
            }
            value.display_name = record[label] || value.display_name;
            if (parentName) {
                const parentValue = record[parentName];
                value.parentId = (Array.isArray(parentValue) ? parentValue[0] : parentValue) || false;
            }
        }
        this._linkTreeNodes(category);
        this.trigger("update");
    },

    /**
     * Rebuilds the children and the roots of the tree from the parent of each node.
     * A node whose parent is not loaded is a root.
     *
     * @param {Object} category
     */
    _linkTreeNodes(category) {
        const nodes = [...category.values.values()].filter((value) => value.id);
        for (const node of nodes) {
            node.childrenIds = [];
        }
        for (const node of nodes) {
            if (node.parentId && category.values.has(node.parentId)) {
                category.values.get(node.parentId).childrenIds.push(node.id);
            }
        }
        category.rootIds = [
            false,
            ...nodes
                .filter((node) => !node.parentId || !category.values.has(node.parentId))
                .map((node) => node.id),
        ];
    },

    /**
     * The ids of a node and of all its loaded descendants.
     *
     * @param {Object} category
     * @param {number} nodeId
     * @returns {number[]}
     */
    _getTreeNodeIds(category, nodeId) {
        const ids = [nodeId];
        const queue = [nodeId];
        while (queue.length) {
            const current = queue.shift();
            for (const childId of category.values.get(current)?.childrenIds ?? []) {
                ids.push(childId);
                queue.push(childId);
            }
        }
        return ids;
    },

    _getCategoryDomain(excludedCategoryId) {
        const domain = [];
        for (const category of this.categories) {
            if (category.id === excludedCategoryId || !category.activeValueId) {
                continue;
            }
            if (category.tree) {
                const ids = this._getTreeNodeIds(category, category.activeValueId);
                domain.push([category.fieldName, "in", ids]);
                continue;
            }
            const field = this.searchViewFields[category.fieldName];
            const operator = field.type === "many2one" && category.parentField ? "child_of" : "=";
            domain.push([category.fieldName, operator, category.activeValueId]);
        }
        return domain;
    },
});
