import { Component, t, useProps, signal } from "@odoo/owl";
import { useDateTimePicker } from "@web/core/components/datetime/datetime_picker_hook";
import { areDatesEqual, deserializeDate, formatDate, parseDate, today } from "@web/core/data/l10n/dates";
import { _t } from "@web/core/data/l10n/translation";
import { registry } from "@web/core/framework/registry";
import { FIELD_WIDTHS } from "@web/views/list/column_width_hook";
import { standardFieldProps } from "@web/views/fields/standard_field_props";

/**
 * Date picker field widget: a text input showing the date in the configured
 * format, with a calendar icon that opens the date picker. The typed text is
 * parsed with the same format, and an invalid text is reverted.
 *
 * <field name="date" widget="datepicker" options="{'format': 'dd/MM/yyyy'}"/>
 */
/**
 * @param {string} value ISO-formatted date or "today"
 */
function parseLimitDate(value) {
    return value === "today" ? today() : deserializeDate(value);
}

export class DatePickerField extends Component {
    static template = "advanced_ui.DatePickerField";

    props = useProps({
        ...standardFieldProps,
        format: t.string().optional(),
        placeholder: t.string().optional(),
        minDate: t.string().optional(),
        maxDate: t.string().optional(),
    });

    inputRef = signal.ref();
    rootRef = signal.ref();

    setup() {
        const getPickerProps = () => this.getPickerProps();
        const picker = useDateTimePicker({
            target: this.rootRef,
            get pickerProps() {
                return getPickerProps();
            },
            onApply: (value) => this.onApply(value),
        });
        this.openPicker = picker.open;
    }

    //-------------------------------------------------------------------------
    // Getters
    //-------------------------------------------------------------------------

    get formattedValue() {
        return formatDate(this.props.record.data[this.props.name], { format: this.props.format });
    }

    /** Earliest and latest accepted dates, when set. */
    get limits() {
        return {
            minDate: this.props.minDate ? parseLimitDate(this.props.minDate) : null,
            maxDate: this.props.maxDate ? parseLimitDate(this.props.maxDate) : null,
        };
    }

    get placeholder() {
        return this.props.placeholder || _t("Pick a date");
    }

    //-------------------------------------------------------------------------
    // Methods
    //-------------------------------------------------------------------------

    getPickerProps() {
        const { minDate, maxDate } = this.limits;
        const pickerProps = {
            value: this.props.record.data[this.props.name],
            type: "date",
            range: false,
            showRangeToggler: false,
        };
        if (minDate) {
            pickerProps.minDate = minDate;
        }
        if (maxDate) {
            pickerProps.maxDate = maxDate;
        }
        return pickerProps;
    }

    /**
     * @param {import("luxon").DateTime} value
     */
    isWithinLimits(value) {
        const { minDate, maxDate } = this.limits;
        return (!minDate || value >= minDate) && (!maxDate || value <= maxDate);
    }

    /**
     * @param {import("luxon").DateTime | false} value
     */
    async onApply(value) {
        if (!areDatesEqual(value, this.props.record.data[this.props.name])) {
            await this.props.record.update({ [this.props.name]: value });
        }
    }

    //-------------------------------------------------------------------------
    // Handlers
    //-------------------------------------------------------------------------

    onCalendarClick() {
        this.openPicker(0);
    }

    /**
     * @param {Event} ev
     */
    async onChange(ev) {
        const text = ev.target.value.trim();
        if (!text) {
            await this.props.record.update({ [this.props.name]: false });
            return;
        }
        let parsed = false;
        try {
            parsed = parseDate(text, { format: this.props.format });
        } catch {
            // The text is not a date in this format: it is reverted below
        }
        if (parsed?.isValid && this.isWithinLimits(parsed)) {
            await this.props.record.update({ [this.props.name]: parsed });
        }
        // Writes the (possibly reverted) value back to the input
        ev.target.value = this.formattedValue;
    }
}

export const datePickerField = {
    component: DatePickerField,
    displayName: _t("Date Picker"),
    supportedTypes: ["date"],
    supportedOptions: [
        {
            label: _t("Display format"),
            name: "format",
            type: "string",
            help: _t(
                `Luxon format of the date, e.g. "dd/MM/yyyy" or "MMM d, yyyy". Defaults to the language date format.`
            ),
        },
        {
            label: _t("Earliest accepted date"),
            name: "min_date",
            type: "string",
            help: _t(`ISO-formatted date (e.g. "2018-12-31") or "%s".`, "today"),
        },
        {
            label: _t("Latest accepted date"),
            name: "max_date",
            type: "string",
            help: _t(`ISO-formatted date (e.g. "2018-12-31") or "%s".`, "today"),
        },
    ],
    extractProps: ({ options, placeholder }) => ({
        format: options.format,
        placeholder,
        minDate: options.min_date,
        maxDate: options.max_date,
    }),
    listViewWidth: () => FIELD_WIDTHS.date,
};

registry.category("fields").add("datepicker", datePickerField);
