import { patch } from "@web/core/utils/patch";
import { SearchPanel } from "@web/search/search_panel/search_panel";
import { SearchArchParser } from "@web/search/search_arch_parser";
import { SearchModel } from "@web/search/search_model";

/**
 * Tree search panel. A `<searchpanel>` field whose related model is hierarchical
 * can name the parent field and the label field of that model:
 *
 * <searchpanel>
 *     <field name="categ_id" tree_parent="parent_id" tree_label="name" limit="200"/>
 * </searchpanel>
 *
 * The values of the field are shown as a tree on the left. Selecting a node
 * filters the records on that node and on all its descendants.
 *
 * The `limit` attribute is the number of nodes loaded at once. When there are
 * more nodes, a "Load more" button loads the next page of `limit` nodes.
 */

const DEFAULT_PARENT = "parent_id";
const DEFAULT_LIMIT = 200;

// Descendants of a node change rarely: they are kept for a while, so that
// selecting the same node again does not ask the server again.
const DESCENDANTS_CACHE_DURATION = 5 * 60 * 1000;

/**
 * @param {number | [number, string] | false} value a many2one value
 * @returns {number | false}
 */
function toId(value) {
    return (Array.isArray(value) ? value[0] : value) || false;
}

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
                    parent: node.getAttribute("tree_parent") || DEFAULT_PARENT,
                    label: node.getAttribute("tree_label") || "display_name",
                };
            }
        }
        return result;
    },
});

patch(SearchModel.prototype, {
    /**
     * Tree categories are loaded here, one page at a time, instead of with
     * search_panel_select_range: that method returns no value at all when the
     * result reaches the limit, which is not what a paged tree needs.
     *
     * @param {Object[]} categories
     */
    async _fetchCategories(categories) {
        const treeCategories = categories.filter((category) => category.tree);
        await super._fetchCategories(categories.filter((category) => !category.tree));
        await Promise.all(treeCategories.map((category) => this._fetchTreeNodes(category)));
    },

    /**
     * Reads one page of nodes: `limit + 1` records are read, the extra one tells
     * whether there is a next page.
     *
     * @param {Object} category
     */
    async _fetchTreeNodes(category) {
        const { label, parent } = category.tree;
        category.pageSize ??= category.limit || DEFAULT_LIMIT;
        category.limit ||= DEFAULT_LIMIT;
        const comodel = this.searchViewFields[category.fieldName].relation;
        const records = await this.orm.searchRead(comodel, [], [...new Set(["id", label, parent])], {
            context: this.globalContext,
            limit: category.limit + 1,
        });
        category.hasMore = records.length > category.limit;
        const values = records.slice(0, category.limit).map((record) => ({
            id: record.id,
            display_name: String(record[label] || record.display_name || record.id),
            [parent]: toId(record[parent]),
        }));
        this._createCategoryTree(category.id, { parent_field: parent, values });
    },

    /**
     * Loads the next page of nodes of a tree.
     *
     * @param {number} sectionId
     */
    async loadMoreTreeValues(sectionId) {
        const category = this.sections.get(sectionId);
        if (!category?.tree) {
            return;
        }
        category.limit += category.pageSize;
        await this._fetchSections([category], []);
        this.trigger("update");
    },

    /**
     * Selects a node of a tree. Its descendants are read from the server before
     * the search runs, so that they are found even if they are not on a loaded page.
     *
     * @param {number} sectionId
     * @param {number} valueId
     */
    async toggleCategoryValue(sectionId, valueId) {
        const category = this.sections.get(sectionId);
        if (!category?.tree) {
            return super.toggleCategoryValue(sectionId, valueId);
        }
        category.activeValueId = valueId;
        const ids = await this._getTreeDescendantIds(category, valueId);
        if (category.activeValueId !== valueId) {
            return;
        }
        category.selection = { valueId, ids };
        this._notify();
    },

    /**
     * The ids of a node and of all its descendants, read level by level.
     *
     * @param {Object} category
     * @param {number} nodeId
     * @returns {Promise<number[]>}
     */
    async _getTreeDescendantIds(category, nodeId) {
        const { parent } = category.tree;
        const comodel = this.searchViewFields[category.fieldName].relation;
        this.treeDescendantsCache ??= new Map();
        const key = `${comodel}|${parent}|${nodeId}`;
        const cached = this.treeDescendantsCache.get(key);
        if (cached && Date.now() - cached.time < DESCENDANTS_CACHE_DURATION) {
            return cached.ids;
        }
        const ids = [nodeId];
        const seen = new Set(ids);
        let frontier = [nodeId];
        while (frontier.length) {
            const records = await this.orm.searchRead(comodel, [[parent, "in", frontier]], ["id"], {
                context: this.globalContext,
            });
            frontier = records.map((record) => record.id).filter((id) => !seen.has(id));
            for (const id of frontier) {
                seen.add(id);
                ids.push(id);
            }
        }
        this.treeDescendantsCache.set(key, { ids, time: Date.now() });
        return ids;
    },

    _getCategoryDomain(excludedCategoryId) {
        const domain = [];
        for (const category of this.categories) {
            if (category.id === excludedCategoryId || !category.activeValueId) {
                continue;
            }
            if (category.tree) {
                const ids =
                    category.selection?.valueId === category.activeValueId
                        ? category.selection.ids
                        : [category.activeValueId];
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

patch(SearchPanel.prototype, {
    loadMoreTreeValues(sectionId) {
        return this.env.searchModel.loadMoreTreeValues(sectionId);
    },
});
