import { Component, onWillStart, onWillUpdateProps, proxy, t, useProps, xml } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { _t } from "@web/core/data/l10n/translation";
import { deserializeDate, deserializeDateTime, serializeDate, serializeDateTime } from "@web/core/data/l10n/dates";
import { mobileViewRegistry } from "@mobile_web/views/registries";
import { parseArch } from "@mobile_web/views/arch";
import { notify } from "@mobile_web/core/notification";
import { buildMonthCells, eventColor, gridRange, groupEventsByDay } from "@mobile_web/views/calendar/calendar_utils";

// 界面文字, 由 _t 包装并通过 i18n/*.po 翻译(模板中用 this.texts 引用)
const TEXTS = {
    prev: _t("Previous month"),
    next: _t("Next month"),
    today: _t("Today"),
    newEvent: _t("New event"),
    allDay: _t("All day"),
    untitled: _t("Untitled"),
    noEvents: _t("No events on this day"),
    loadFailed: _t("Failed to load, please try again"),
};

/** 一天的第一个事件默认开始的时刻 (新建事件时使用) */
const DEFAULT_START_HOUR = 9;

/** 字段值 (many2one 为 [id, name]) 转为显示文字 */
function displayValue(value) {
    if (Array.isArray(value)) {
        return value[1] ?? "";
    }
    return value === false || value === undefined || value === null ? "" : String(value);
}

/**
 * 移动端日历视图: 月历格子 + 选中日期的事件列表.
 *
 * arch 属性: date_start (必须), date_stop, all_day, color; 第一个非日期字段作为事件标题, 没有时使用显示名称.
 * 跨天事件出现在它覆盖的每一天. 只显示开始日期落在当前月历格子范围内的事件.
 */
export class MobileCalendarView extends Component {
    texts = TEXTS;
    static template = xml`
        <t t-name="mobile_web.MobileCalendarView">
            <div class="m_cal">
                <div class="m_cal_head">
                    <button type="button" class="m_cal_nav" data-dir="-1" t-att-aria-label="this.texts.prev" t-on-click="this.onNav">
                        <svg viewBox="0 0 16 16" width="16" height="16" aria-hidden="true"><path d="M10 3.5 5.5 8 10 12.5" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>
                    </button>
                    <strong class="m_cal_title"><t t-esc="this.monthTitle"/></strong>
                    <button type="button" class="m_cal_nav" data-dir="1" t-att-aria-label="this.texts.next" t-on-click="this.onNav">
                        <svg viewBox="0 0 16 16" width="16" height="16" aria-hidden="true"><path d="M6 3.5 10.5 8 6 12.5" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>
                    </button>
                    <button type="button" class="m_cal_today" t-on-click="this.onToday"><t t-esc="this.texts.today"/></button>
                </div>
                <div class="m_cal_weekdays">
                    <span t-foreach="this.weekdays" t-as="weekday" t-key="weekday_index"><t t-esc="weekday"/></span>
                </div>
                <div class="m_cal_grid">
                    <button type="button" t-foreach="this.cells" t-as="cell" t-key="cell.key"
                            t-attf-class="m_cal_day {{ cell.inMonth ? '' : 'is_other' }} {{ cell.isToday ? 'is_today' : '' }} {{ cell.isSelected ? 'is_selected' : '' }}"
                            t-att-data-day="cell.key" t-on-click="this.onSelectDay">
                        <span class="m_cal_day_num"><t t-esc="cell.day"/></span>
                        <span class="m_cal_dots">
                            <span t-foreach="cell.dots" t-as="dot" t-key="dot_index" class="m_cal_dot" t-att-style="'background:' + dot"/>
                        </span>
                    </button>
                </div>
                <div class="m_cal_agenda_head">
                    <span class="m_cal_agenda_date"><t t-esc="this.selectedTitle"/></span>
                    <button type="button" class="m_cal_add" t-att-aria-label="this.texts.newEvent" t-att-title="this.texts.newEvent" t-on-click="this.onAdd">
                        <svg viewBox="0 0 16 16" width="16" height="16" aria-hidden="true"><path d="M8 3v10M3 8h10" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg>
                    </button>
                </div>
                <ul class="m_cal_agenda">
                    <li t-foreach="this.agenda" t-as="event" t-key="event.id + ':' + this.selectedKey">
                        <button type="button" class="m_cal_event" t-att-data-id="event.id" t-on-click="this.onRowClick">
                            <span class="m_cal_event_bar" t-att-style="'background:' + event.color"/>
                            <span class="m_cal_event_time"><t t-esc="event.timeLabel"/></span>
                            <span class="m_cal_event_title"><t t-esc="event.title"/></span>
                        </button>
                    </li>
                </ul>
                <p t-if="!this.agenda.length and !this.state.loading and !this.state.error" class="m_empty"><t t-esc="this.texts.noEvents"/></p>
                <p t-if="this.state.error" class="m_error"><t t-esc="this.texts.loadFailed"/></p>
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
        onCreate: t.function(),
    });
    orm = useService("orm");
    notification = useService("notification");
    state = proxy({
        month: luxon.DateTime.local().startOf("month"),
        selected: luxon.DateTime.local().startOf("day"),
        records: [],
        loading: false,
        error: false,
    });

    setup() {
        const node = parseArch(this.props.arch);
        this.dateStart = node.attrs.date_start;
        this.dateStop = node.attrs.date_stop || null;
        this.allDayField = node.attrs.all_day || null;
        this.colorField = node.attrs.color || null;
        const titleNode = node.children.find(
            (c) => c.tag === "field" && c.attrs.name && ![this.dateStart, this.dateStop, this.allDayField].includes(c.attrs.name)
        );
        this.titleField = titleNode ? titleNode.attrs.name : null;
        this.dateOnly = this.props.fields[this.dateStart]?.type === "date";
        this.fieldNames = [...new Set([this.dateStart, this.dateStop, this.allDayField, this.colorField, this.titleField, "display_name"].filter(Boolean))];
        this.weekdays = luxon.Info.weekdays("short");
        onWillStart(() => this.load(this.props));
        // reload only when the search domain changes; the month is changed by the view itself
        onWillUpdateProps((nextProps) => {
            if (JSON.stringify(nextProps.domain) !== JSON.stringify(this.props.domain)) {
                return this.load(nextProps);
            }
        });
    }

    /** 当前月历格子覆盖的范围, 作为查询条件 */
    rangeDomain() {
        const { start, end } = gridRange(this.state.month);
        const format = this.dateOnly ? serializeDate : serializeDateTime;
        return [
            [this.dateStart, ">=", format(start)],
            [this.dateStart, "<", format(end)],
        ];
    }

    async load(props) {
        this.state.loading = true;
        this.state.error = false;
        try {
            this.state.records = await this.orm.searchRead(
                props.resModel,
                [...(props.domain || []), ...this.rangeDomain()],
                this.fieldNames,
                { order: `${this.dateStart} asc`, context: props.context || {} }
            );
        } catch (error) {
            this.state.error = true;
            notify(this.notification, error?.data?.message || error?.message || this.texts.loadFailed, { type: "danger" });
        } finally {
            this.state.loading = false;
        }
    }

    parseDate(value) {
        if (!value) {
            return null;
        }
        return this.dateOnly ? deserializeDate(value) : deserializeDateTime(value);
    }

    /** 数据库记录 -> 日历事件 */
    toEvent(record) {
        const start = this.parseDate(record[this.dateStart]);
        if (!start) {
            return null;
        }
        const allDay = this.dateOnly || (this.allDayField ? Boolean(record[this.allDayField]) : false);
        const stop = (this.dateStop && this.parseDate(record[this.dateStop])) || start;
        const title = this.titleField ? displayValue(record[this.titleField]) : displayValue(record.display_name);
        return {
            id: record.id,
            start: allDay ? start.startOf("day") : start,
            stop: allDay ? stop.startOf("day") : stop,
            allDay,
            title: title || this.texts.untitled,
            timeLabel: allDay ? this.texts.allDay : start.toFormat("HH:mm"),
            color: eventColor(this.colorField ? record[this.colorField] : undefined),
        };
    }

    get byDay() {
        const events = this.state.records.map((record) => this.toEvent(record)).filter(Boolean);
        return groupEventsByDay(events);
    }

    get selectedKey() {
        return this.state.selected.toISODate();
    }

    get agenda() {
        return this.byDay.get(this.selectedKey) || [];
    }

    get monthTitle() {
        return this.state.month.toFormat("LLLL yyyy");
    }

    get selectedTitle() {
        return this.state.selected.toFormat("cccc, LLL d");
    }

    get cells() {
        const byDay = this.byDay;
        const selectedKey = this.selectedKey;
        return buildMonthCells(this.state.month, luxon.DateTime.local()).map((cell) => {
            const events = byDay.get(cell.key) || [];
            return {
                ...cell,
                dots: events.slice(0, 3).map((event) => event.color),
                isSelected: cell.key === selectedKey,
            };
        });
    }

    onNav(ev) {
        const direction = Number(ev.currentTarget.dataset.dir);
        const month = this.state.month.plus({ months: direction }).startOf("month");
        const day = Math.min(this.state.selected.day, month.daysInMonth);
        this.state.selected = month.set({ day });
        this.state.month = month;
        return this.load(this.props);
    }

    onToday() {
        const today = luxon.DateTime.local().startOf("day");
        const monthChanged = today.toISODate().slice(0, 7) !== this.state.month.toISODate().slice(0, 7);
        this.state.selected = today;
        if (monthChanged) {
            this.state.month = today.startOf("month");
            return this.load(this.props);
        }
    }

    onSelectDay(ev) {
        const day = luxon.DateTime.fromISO(ev.currentTarget.dataset.day).startOf("day");
        this.state.selected = day;
        if (day.toISODate().slice(0, 7) !== this.state.month.toISODate().slice(0, 7)) {
            this.state.month = day.startOf("month");
            return this.load(this.props);
        }
    }

    onRowClick(ev) {
        this.props.onSelect(Number(ev.currentTarget.dataset.id));
    }

    /** 新建事件: 开始时间为选中的日期, 默认值通过 context 的 default_ 键传给表单 */
    onAdd() {
        const day = this.state.selected;
        const defaults = {};
        if (this.dateOnly) {
            defaults[`default_${this.dateStart}`] = serializeDate(day);
        } else {
            const start = day.set({ hour: DEFAULT_START_HOUR, minute: 0, second: 0, millisecond: 0 });
            defaults[`default_${this.dateStart}`] = serializeDateTime(start);
            if (this.dateStop) {
                defaults[`default_${this.dateStop}`] = serializeDateTime(start.plus({ hours: 1 }));
            }
        }
        this.props.onCreate(defaults);
    }
}

mobileViewRegistry.add("calendar", MobileCalendarView);
