import { Component, proxy, signal, t, useProps } from "@odoo/owl";
import { _t } from "@web/core/data/l10n/translation";
import { registry } from "@web/core/framework/registry";
import { standardFieldProps } from "@web/views/fields/standard_field_props";

/**
 * Time picker: a text input with a clock icon. A list of the times of the day, at
 * the given step, is shown under the input and filtered by the text typed. The
 * value is a text "HH:MM".
 *
 * <TimePicker value="'09:30'" step="30" onChange="onTimeChange"/>
 */

const DEFAULT_STEP = 30;
const MINUTES_PER_DAY = 24 * 60;

/** The times of the day from 00:00, at the step (in minutes). */
export function timesOfDay(step = DEFAULT_STEP) {
    const times = [];
    for (let minutes = 0; minutes < MINUTES_PER_DAY; minutes += step) {
        const hours = String(Math.floor(minutes / 60)).padStart(2, "0");
        const mins = String(minutes % 60).padStart(2, "0");
        times.push(`${hours}:${mins}`);
    }
    return times;
}

/**
 * Parses a typed time: "9:30", "09:30", "0930", "9" or "9.5" (hours). Returns the
 * text "HH:MM", or false when the text is not a valid time.
 *
 * @param {string} text
 * @returns {string | false}
 */
export function parseTime(text) {
    const value = text.trim();
    const match = value.match(/^(\d{1,2})(?:[:.h]?(\d{1,2}))?$/i);
    if (!match) {
        return false;
    }
    let hours = Number(match[1]);
    let minutes = match[2] === undefined ? 0 : Number(match[2]);
    if (value.includes(".") && match[2] !== undefined) {
        // "9.5" is nine hours and a half, not nine hours and five minutes
        minutes = Math.round(Number(`0.${match[2]}`) * 60);
    }
    if (match[2] === undefined && value.length === 4 && /^\d{4}$/.test(value)) {
        // "0930"
        hours = Number(value.slice(0, 2));
        minutes = Number(value.slice(2));
    }
    if (hours > 23 || minutes > 59) {
        return false;
    }
    return `${String(hours).padStart(2, "0")}:${String(minutes).padStart(2, "0")}`;
}

/**
 * The times matching the text: a time starting with it, or with its hour padded.
 *
 * @param {string[]} times
 * @param {string} text
 */
export function filterTimes(times, text) {
    const query = text.trim();
    if (!query) {
        return times;
    }
    const padded = /^\d$/.test(query) ? `0${query}` : query;
    return times.filter((time) => time.startsWith(query) || time.startsWith(padded));
}

export class TimePicker extends Component {
    static template = "advanced_ui.TimePicker";

    props = useProps({
        id: t.string().optional(),
        name: t.string().optional(),
        value: t.string().optional(),
        step: t.number().optional(),
        placeholder: t.string().optional(),
        readonly: t.boolean().optional(),
        onChange: t.function().optional(),
    });

    inputRef = signal.ref();

    setup() {
        // While the user types, the text is their own; otherwise it is the value
        this.state = proxy({ text: "", typing: false, open: false, highlight: -1 });
    }

    /** The text of the input: what is typed, or the value. */
    get currentText() {
        return this.state.typing ? this.state.text : this.props.value || "";
    }

    get times() {
        return timesOfDay(this.props.step || DEFAULT_STEP);
    }

    /** The times shown in the list: all of them, or those matching the typed text. */
    get options() {
        return filterTimes(this.times, this.state.typing ? this.state.text : "");
    }

    setValue(time) {
        this.state.typing = false;
        this.state.text = "";
        this.props.onChange?.(time);
    }

    /** Commits the typed text: a valid time is set, anything else is reverted. */
    commitText() {
        if (!this.state.typing) {
            return;
        }
        const time = parseTime(this.state.text);
        if (time) {
            this.setValue(time);
        } else {
            this.state.typing = false;
            this.state.text = "";
        }
    }

    onFocus() {
        this.state.open = true;
        this.state.highlight = -1;
    }

    onBlur() {
        this.commitText();
        this.state.open = false;
        this.state.highlight = -1;
    }

    onInput(ev) {
        this.state.text = ev.target.value;
        this.state.typing = true;
        this.state.open = true;
        this.state.highlight = -1;
    }

    onKeydown(ev) {
        const count = this.options.length;
        if (ev.key === "ArrowDown" || ev.key === "ArrowUp") {
            ev.preventDefault();
            this.state.open = true;
            if (!count) {
                return;
            }
            const step = ev.key === "ArrowDown" ? 1 : -1;
            this.state.highlight = (this.state.highlight + step + count) % count;
        } else if (ev.key === "Enter") {
            ev.preventDefault();
            if (this.state.open && this.state.highlight >= 0) {
                this.setValue(this.options[this.state.highlight]);
            } else {
                this.commitText();
            }
            this.state.open = false;
        } else if (ev.key === "Escape") {
            this.state.open = false;
            this.state.typing = false;
            this.state.text = "";
        }
    }

    /** The mousedown keeps the focus on the input, so that the choice is not lost. */
    onOptionMouseDown(ev, time) {
        ev.preventDefault();
        this.setValue(time);
        this.state.open = false;
        this.inputRef()?.blur();
    }
}

/** Hours (a float, like 9.5) as the text "09:30". */
export function hoursToText(hours) {
    if (!hours && hours !== 0) {
        return "";
    }
    const minutes = Math.round(hours * 60);
    return `${String(Math.floor(minutes / 60)).padStart(2, "0")}:${String(minutes % 60).padStart(2, "0")}`;
}

/** The text "HH:MM" as hours (a float, like 9.5). */
export function textToHours(text) {
    const [hours, minutes] = text.split(":").map(Number);
    return Math.round((hours + minutes / 60) * 100) / 100;
}

/**
 * Field widget for a char field (the text "HH:MM") or a float field (hours).
 *
 * <field name="start" widget="timepicker" options="{'step': 15}"/>
 */
export class TimePickerField extends Component {
    static template = "advanced_ui.TimePickerField";
    static components = { TimePicker };

    props = useProps({ ...standardFieldProps, step: t.number().optional() });

    get isFloat() {
        return this.props.record.fields[this.props.name].type === "float";
    }

    get text() {
        const value = this.props.record.data[this.props.name];
        return this.isFloat ? hoursToText(value) : value || "";
    }

    async onChange(time) {
        let value = time || (this.isFloat ? false : "");
        if (this.isFloat && time) {
            value = textToHours(time);
        }
        await this.props.record.update({ [this.props.name]: value });
    }
}

registry.category("fields").add("timepicker", {
    component: TimePickerField,
    displayName: _t("Time Picker"),
    supportedTypes: ["char", "float"],
    supportedOptions: [
        {
            label: _t("Step (minutes)"),
            name: "step",
            type: "number",
            default: DEFAULT_STEP,
            help: _t("The distance between two times of the list, in minutes."),
        },
    ],
    extractProps: ({ options }) => ({ step: options.step }),
});
