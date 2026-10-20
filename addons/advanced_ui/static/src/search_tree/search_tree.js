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

// Labels and parents of the tree nodes change rarely: they are kept for a while
// so that a reload of the search panel does not read them again.
const TREE_CACHE_DURATION = 5 * 60 * 1000;

patch(SearchModel.prototype, {
    _createCategoryTree(sectionId, result) {
        super._createCategoryTree(sectionId, result);
        const category = this.sections.get(sectionId);
        if (!category.tree) {
            return;
        }
        // The parent field of the comodel, as the server knows it
        category.comodelParent = result.parent_field || false;
        if (category.tree.parent) {
            category.parentField = category.tree.parent;
        }
        this._loadTreeNodes(category);
    },

    /**
     * Returns the cache of the tree nodes of a comodel for the given label and parent.
     *
     * @param {string} key
     * @returns {Map<number, Object>}
     */
    _getTreeNodeCache(key) {
        this.treeNodeCaches ??= new Map();
        if (!this.treeNodeCaches.has(key)) {
            this.treeNodeCaches.set(key, new Map());
        }
        return this.treeNodeCaches.get(key);
    },

    /**
     * Reads the label and the parent of the nodes that are not cached yet, so that
     * the tree shows the configured label and follows the configured parent field.
     *
     * @param {Object} category
     */
    async _loadTreeNodes(category) {
        const { label, parent } = category.tree;
        const parentName = parent || category.comodelParent;
        const ids = [...category.values.keys()].filter(Boolean);
        if (!ids.length) {
            return;
        }
        const loadId = (category.treeLoadId = (category.treeLoadId || 0) + 1);
        const comodel = this.searchViewFields[category.fieldName].relation;
        const cache = this._getTreeNodeCache(`${comodel}|${label}|${parentName}`);
        const now = Date.now();
        const isFresh = (id) => cache.has(id) && now - cache.get(id).time < TREE_CACHE_DURATION;
        const missingIds = ids.filter((id) => !isFresh(id));
        if (missingIds.length) {
            const fields = [...new Set([label, parentName].filter(Boolean))];
            const records = await this.orm.read(comodel, missingIds, fields, {
                context: this.globalContext,
            });
            for (const record of records) {
                const parentValue = parentName ? record[parentName] : false;
                cache.set(record.id, {
                    label: record[label],
                    parentId: (Array.isArray(parentValue) ? parentValue[0] : parentValue) || false,
                    time: now,
                });
            }
        }
        if (loadId !== category.treeLoadId) {
            return;
        }
        for (const id of ids) {
            const value = category.values.get(id);
            const node = cache.get(id);
            if (!value || !node) {
                continue;
            }
            value.display_name = node.label || value.display_name;
            if (parentName) {
                value.parentId = node.parentId;
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

    /**
     * The condition of a selected node. When the tree follows the parent field of the
     * comodel, the server expands the node into its descendants with child_of, which
     * does not send the ids of the tree. Otherwise, the loaded descendants are sent.
     *
     * @param {Object} category
     * @returns {Array}
     */
    _getTreeCategoryCondition(category) {
        const { activeValueId, fieldName, tree } = category;
        const followsComodelParent = (tree.parent || false) === (category.comodelParent || false);
        if (followsComodelParent && category.comodelParent) {
            return [fieldName, "child_of", activeValueId];
        }
        return [fieldName, "in", this._getTreeNodeIds(category, activeValueId)];
    },

    _getCategoryDomain(excludedCategoryId) {
        const domain = [];
        for (const category of this.categories) {
            if (category.id === excludedCategoryId || !category.activeValueId) {
                continue;
            }
            if (category.tree) {
                domain.push(this._getTreeCategoryCondition(category));
                continue;
            }
            const field = this.searchViewFields[category.fieldName];
            const operator = field.type === "many2one" && category.parentField ? "child_of" : "=";
            domain.push([category.fieldName, operator, category.activeValueId]);
        }
        return domain;
    },
});
