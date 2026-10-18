import { AutoComplete } from "@web/core/components/autocomplete/autocomplete";
import { Many2XAutocomplete } from "@web/views/fields/relational_utils";

const TILE_COLORS = ["#5b6bdf", "#e8562a", "#2ea44f", "#c0392b", "#8e44ad", "#16a085"];

/**
 * Autocomplete of the "lookup" many2one widget: the same suggestions as the default
 * dropdown, drawn as rows with a colored tile, the display name and a subtitle.
 */
export class LookupAutocomplete extends Many2XAutocomplete {
    static template = "advanced_ui.LookupAutocomplete";
    static components = { AutoComplete };

    get optionsSource() {
        return { ...super.optionsSource, optionSlot: "lookupOption" };
    }

    /** Name of the related field shown as subtitle, given by the "subtitle" option. */
    get subtitleField() {
        return Object.keys(this.props.specification || {})[0];
    }

    getSubtitle(record) {
        const value = record[this.subtitleField];
        return Array.isArray(value) ? value[1] : value || "";
    }

    getTileInitial(record) {
        return (record.display_name || "?").trim().charAt(0).toUpperCase();
    }

    getTileColor(record) {
        return TILE_COLORS[Math.abs(record.id || 0) % TILE_COLORS.length];
    }
}
