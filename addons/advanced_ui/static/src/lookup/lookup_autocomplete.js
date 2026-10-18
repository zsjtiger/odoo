import { t, useProps } from "@odoo/owl";
import { _t } from "@web/core/data/l10n/translation";
import { AutoComplete } from "@web/core/components/autocomplete/autocomplete";
import { Many2XAutocomplete, many2XAutocompleteProps } from "@web/views/fields/relational_utils";

const TILE_COLORS = ["#5b6bdf", "#e8562a", "#2ea44f", "#c0392b", "#8e44ad", "#16a085"];

/**
 * Autocomplete of the "lookup" many2one widget: the same suggestions as the default
 * dropdown, drawn as rows with a colored tile, the display name and a subtitle. When a
 * group field is given, the rows are split under a header for each value of that field.
 */
export class LookupAutocomplete extends Many2XAutocomplete {
    static template = "advanced_ui.LookupAutocomplete";
    static components = { AutoComplete };

    props = useProps({
        ...many2XAutocompleteProps,
        lookupFields: t.object().optional(),
    });

    get optionsSource() {
        return { ...super.optionsSource, optionSlot: "lookupOption" };
    }

    get subtitleField() {
        return this.props.lookupFields?.subtitle;
    }

    get groupField() {
        return this.props.lookupFields?.group;
    }

    async suggest(request, lock) {
        const suggestions = await super.suggest(request, lock);
        if (!this.groupField) {
            return suggestions;
        }
        const grouped = [];
        const seenGroups = new Set();
        for (const suggestion of suggestions) {
            if (!suggestion.data?.record) {
                grouped.push(suggestion);
                continue;
            }
            const group = this.getGroupName(suggestion.data.record);
            if (!seenGroups.has(group)) {
                seenGroups.add(group);
                grouped.push({
                    cssClass: "o_lookup_group_header",
                    data: { header: true },
                    label: group,
                });
            }
            grouped.push(suggestion);
        }
        return grouped;
    }

    getGroupName(record) {
        return this.getFieldText(record, this.groupField) || _t("Other");
    }

    getSubtitle(record) {
        return this.getFieldText(record, this.subtitleField);
    }

    getFieldText(record, fieldName) {
        const value = fieldName ? record[fieldName] : "";
        return Array.isArray(value) ? value[1] : value || "";
    }

    getTileInitial(record) {
        return (record.display_name || "?").trim().charAt(0).toUpperCase();
    }

    getTileColor(record) {
        return TILE_COLORS[Math.abs(record.id || 0) % TILE_COLORS.length];
    }
}
