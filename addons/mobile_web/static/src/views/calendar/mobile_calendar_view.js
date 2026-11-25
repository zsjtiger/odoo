import { Component, onMounted, onWillStart, onWillUnmount, onWillUpdateProps, proxy, signal, t, useProps, xml } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { _t } from "@web/core/data/l10n/translation";
import { deserializeDate, deserializeDateTime, serializeDate, serializeDateTime } from "@web/core/data/l10n/dates";
import { mobileViewRegistry } from "@mobile_web/views/registries";
import { parseArch } from "@mobile_web/views/arch";
import { notify } from "@mobile_web/core/notification";
import {
    buildMonthCells,
    buildWeekCells,
    eventColor,
    gridRange,
    groupEventsByDay,
    HOUR_HEIGHT,
    isMultiDay,
    layoutMonthBars,
    layoutTimedEvents,
    MIN_BLOCK_HEIGHT,
    SNAP_MINUTES,
    snapMinutes,
    weekRange,
} from "@mobile_web/views/calendar/calendar_utils";

// 界面文字, 由 _t 包装并通过 i18n/*.po 翻译(模板中用 this.texts 引用)
const TEXTS = {
    prev: _t("Previous"),
    next: _t("Next"),
    today: _t("Today"),
    day: _t("Day"),
    week: _t("Week"),
    month: _t("Month"),
    newEvent: _t("New event"),
    allDay: _t("All day"),
    untitled: _t("Untitled"),
    noEvents: _t("No events on this day"),
    loadFailed: _t("Failed to load, please try again"),
    saveFailed: _t("Could not move the event"),
    continues: _t("Continues"),
    endsAt: _t("Ends"),
};

/** 一天的第一个事件默认开始的时刻 (新建事件时使用) */
const DEFAULT_START_HOUR = 9;
/** 长按多久后开始拖动事件 (毫秒); 在此之前移动手指视为滚动 */
const LONG_PRESS_MS = 400;
/** 长按前允许的最大移动距离 (px) */
const SCROLL_TOLERANCE = 8;

/** 字段值 (many2one 为 [id, name]) 转为显示文字 */
function displayValue(value) {
    if (Array.isArray(value)) {
        return value[1] ?? "";
    }
    return value === false || value === undefined || value === null ? "" : String(value);
}

const HOUR_LABELS = Array.from({ length: 24 }, (_, hour) => ({
    hour,
    label: `${String(hour).padStart(2, "0")}:00`,
    top: hour * HOUR_HEIGHT,
}));

/**
 * 移动端日历视图: 日视图 / 周视图 / 月视图.
 *
 * - 月视图: 月历格子 + 选中日期的事件列表
 * - 周视图: 7 天 + 选中日期的时间轴
 * - 日视图: 选中日期的时间轴
 *
 * 时间轴上的事件按时长定位, 同一时段重叠的事件并排显示. 长按事件后可以上下拖动改时间,
 * 拖动底部的把手可以改时长 (需要 date_stop 字段). 全天事件和纯日期的事件不能拖动.
 *
 * arch 属性: date_start (必须), date_stop, all_day, color; 第一个非日期字段作为事件标题, 没有时使用显示名称.
 */
export class MobileCalendarView extends Component {
    texts = TEXTS;
    static template = xml`
        <t t-name="mobile_web.MobileCalendarView">
            <div class="m_cal" t-ref="this.root">
                <!-- sticky header: navigation and mode; the week strip and the day header of the selected day -->
                <div class="m_cal_sticky">
                    <div class="m_cal_head">
                        <button type="button" class="m_cal_nav" data-dir="-1" t-att-aria-label="this.texts.prev" t-on-click="this.onNav">
                            <svg viewBox="0 0 16 16" width="16" height="16" aria-hidden="true"><path d="M10 3.5 5.5 8 10 12.5" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>
                        </button>
                        <strong class="m_cal_title"><t t-esc="this.title"/></strong>
                        <button type="button" class="m_cal_nav" data-dir="1" t-att-aria-label="this.texts.next" t-on-click="this.onNav">
                            <svg viewBox="0 0 16 16" width="16" height="16" aria-hidden="true"><path d="M6 3.5 10.5 8 6 12.5" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>
                        </button>
                        <button type="button" class="m_cal_today" t-on-click="this.onToday"><t t-esc="this.texts.today"/></button>
                    </div>
                    <div class="m_cal_modes" role="group">
                        <button type="button" t-attf-class="m_cal_mode {{ this.state.mode === 'day' ? 'is_active' : '' }}" data-mode="day" t-on-click="this.onMode"><t t-esc="this.texts.day"/></button>
                        <button type="button" t-attf-class="m_cal_mode {{ this.state.mode === 'week' ? 'is_active' : '' }}" data-mode="week" t-on-click="this.onMode"><t t-esc="this.texts.week"/></button>
                        <button type="button" t-attf-class="m_cal_mode {{ this.state.mode === 'month' ? 'is_active' : '' }}" data-mode="month" t-on-click="this.onMode"><t t-esc="this.texts.month"/></button>
                    </div>
                    <t t-if="this.state.mode === 'week'">
                        <div class="m_cal_grid m_cal_week_grid">
                            <button type="button" t-foreach="this.weekCells" t-as="cell" t-key="cell.key"
                                    t-attf-class="m_cal_day m_cal_week_day {{ cell.isToday ? 'is_today' : '' }} {{ cell.isSelected ? 'is_selected' : '' }}"
                                    t-att-data-day="cell.key" t-on-click="this.onSelectDay">
                                <span class="m_cal_day_name"><t t-esc="cell.weekday"/></span>
                                <span class="m_cal_day_num"><t t-esc="cell.day"/></span>
                                <span class="m_cal_dots">
                                    <span t-foreach="cell.dots" t-as="dot" t-key="dot_index" class="m_cal_dot" t-att-style="'background:' + dot"/>
                                </span>
                            </button>
                        </div>
                    </t>
                    <div t-if="this.state.mode !== 'month'" class="m_cal_agenda_head">
                        <span class="m_cal_agenda_date"><t t-esc="this.selectedTitle"/></span>
                        <button type="button" class="m_cal_add" t-att-aria-label="this.texts.newEvent" t-att-title="this.texts.newEvent" t-on-click="this.onAdd">
                            <svg viewBox="0 0 16 16" width="16" height="16" aria-hidden="true"><path d="M8 3v10M3 8h10" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg>
                        </button>
                    </div>
                </div>

                <!-- month: month grid, the day header and the events of the selected day -->
                <t t-if="this.state.mode === 'month'">
                    <div class="m_cal_weekdays">
                        <span t-foreach="this.weekdays" t-as="weekday" t-key="weekday_index"><t t-esc="weekday"/></span>
                    </div>
                    <div class="m_cal_grid m_cal_month_grid">
                        <button type="button" t-foreach="this.monthCells" t-as="cell" t-key="cell.key"
                                t-attf-class="m_cal_day {{ cell.inMonth ? '' : 'is_other' }} {{ cell.isToday ? 'is_today' : '' }} {{ cell.isSelected ? 'is_selected' : '' }}"
                                t-att-data-day="cell.key" t-on-click="this.onSelectDay">
                            <span class="m_cal_day_num"><t t-esc="cell.day"/></span>
                            <span class="m_cal_dots">
                                <span t-foreach="cell.dots" t-as="dot" t-key="dot_index" class="m_cal_dot" t-att-style="'background:' + dot"/>
                            </span>
                        </button>
                        <div class="m_cal_bars">
                            <button type="button" t-foreach="this.monthBars" t-as="bar" t-key="bar.key" class="m_cal_bar"
                                    t-att-style="bar.style" t-att-data-id="bar.event.id" t-on-click="this.onRowClick">
                                <t t-esc="bar.event.title"/>
                            </button>
                        </div>
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
                </t>

                <!-- day and week: timeline of the selected day -->
                <t t-else="">
                    <div class="m_cal_timeline">
                        <div t-if="this.allDayEvents.length" class="m_cal_allday">
                            <span class="m_cal_hour_label"><t t-esc="this.texts.allDay"/></span>
                            <div class="m_cal_allday_events">
                                <button type="button" t-foreach="this.allDayEvents" t-as="event" t-key="event.id" class="m_cal_event" t-att-data-id="event.id" t-on-click="this.onRowClick">
                                    <span class="m_cal_event_bar" t-att-style="'background:' + event.color"/>
                                    <span class="m_cal_event_title"><t t-esc="event.title"/></span>
                                </button>
                            </div>
                        </div>
                        <div class="m_cal_time_grid" t-att-style="'height:' + this.gridHeight + 'px'">
                            <div t-foreach="this.hourLabels" t-as="row" t-key="row.hour" class="m_cal_hour_mark" t-att-style="'top:' + row.top + 'px'">
                                <span class="m_cal_hour_label"><t t-esc="row.label"/></span>
                            </div>
                            <div t-foreach="this.blocks" t-as="block" t-key="block.event.id"
                                 t-attf-class="m_cal_block {{ this.state.drag and this.state.drag.id === block.event.id and this.state.drag.active ? 'is_dragging' : '' }} {{ this.canDrag ? 'is_draggable' : '' }}"
                                 t-att-style="block.style" t-att-data-id="block.event.id"
                                 t-on-click="this.onBlockClick" t-on-pointerdown="this.onBlockPointerDown">
                                <span class="m_cal_block_time"><t t-esc="block.event.timeLabel"/></span>
                                <span class="m_cal_block_title"><t t-esc="block.event.title"/></span>
                                <span t-if="this.canResize" class="m_cal_resize" t-att-data-id="block.event.id" t-on-pointerdown="this.onResizePointerDown"/>
                            </div>
                        </div>
                    </div>
                </t>

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
        mode: "month",
        // the selected day decides the shown day, week or month
        selected: luxon.DateTime.local().startOf("day"),
        records: [],
        loading: false,
        error: false,
        // the event being moved or resized: { id, mode: "move" | "resize", delta (minutes), active, moved }
        drag: null,
    });
    hourLabels = HOUR_LABELS;
    gridHeight = 24 * HOUR_HEIGHT;

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
        // timed events on a datetime field can be moved, and resized when there is a stop field
        this.canDrag = !this.dateOnly;
        this.canResize = this.canDrag && Boolean(this.dateStop);
        this.fieldNames = [...new Set([this.dateStart, this.dateStop, this.allDayField, this.colorField, this.titleField, "display_name"].filter(Boolean))];
        this.weekdays = luxon.Info.weekdays("short");
        this.loadedRange = null;
        this.root = signal.ref();
        this.justDragged = false;
        this.timer = null;
        this.dragContext = null;

        // the controller keeps its search bar sticky at the top: the calendar header sticks below it
        let observer = null;
        onMounted(() => {
            const bar = this.root()?.closest(".m_act_window_controller")?.querySelector(".m_search_bar");
            if (bar && typeof ResizeObserver !== "undefined") {
                observer = new ResizeObserver(() => this.setStickyTop(bar));
                observer.observe(bar);
            }
            if (bar) {
                this.setStickyTop(bar);
            }
        });
        onWillUnmount(() => {
            observer?.disconnect();
            this.endDrag();
        });
        onWillStart(() => this.load(this.props));
        // reload only when the search domain changes; the period is changed by the view itself
        onWillUpdateProps((nextProps) => {
            if (JSON.stringify(nextProps.domain) !== JSON.stringify(this.props.domain)) {
                return this.load(nextProps, true);
            }
        });
    }

    setStickyTop(bar) {
        this.root()?.style.setProperty("--m_cal_sticky_top", `${bar.offsetHeight}px`);
    }

    /** 当前显示范围: 日视图为选中的一天, 周视图为一周, 月视图为月历格子覆盖的范围 */
    get range() {
        const selected = this.state.selected;
        if (this.state.mode === "day") {
            return { start: selected.startOf("day"), end: selected.startOf("day").plus({ days: 1 }) };
        }
        if (this.state.mode === "week") {
            return weekRange(selected);
        }
        return gridRange(selected.startOf("month"));
    }

    /** 查询条件: 显示范围内开始的事件 */
    rangeDomain(range = this.range) {
        const format = this.dateOnly ? serializeDate : serializeDateTime;
        return [
            [this.dateStart, ">=", format(range.start)],
            [this.dateStart, "<", format(range.end)],
        ];
    }

    /**
     * 按显示范围查询事件. 范围没有变化时不重复查询, force 为 true 时始终查询
     */
    async load(props, force = false) {
        const range = this.range;
        const key = `${props.resModel}|${JSON.stringify(props.domain || [])}|${range.start.toISODate()}|${range.end.toISODate()}`;
        if (!force && key === this.loadedRange) {
            return;
        }
        this.loadedRange = key;
        this.state.loading = true;
        this.state.error = false;
        try {
            this.state.records = await this.orm.searchRead(
                props.resModel,
                [...(props.domain || []), ...this.rangeDomain(range)],
                this.fieldNames,
                { order: `${this.dateStart} asc`, context: props.context || {} }
            );
        } catch (error) {
            this.state.error = true;
            this.loadedRange = null;
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

    get events() {
        return this.state.records.map((record) => this.toEvent(record)).filter(Boolean);
    }

    get byDay() {
        return groupEventsByDay(this.events);
    }

    get selectedKey() {
        return this.state.selected.toISODate();
    }

    /**
     * 选中日期的事件, 时间标签按这一天来写 (跨天事件在开始日、中间日、结束日的标签不同)
     */
    get agenda() {
        const day = this.state.selected;
        return (this.byDay.get(this.selectedKey) || []).map((event) => ({
            ...event,
            timeLabel: this.labelFor(event, day),
        }));
    }

    labelFor(event, day) {
        if (event.allDay) {
            return event.timeLabel;
        }
        const dayStart = day.startOf("day");
        const dayEnd = dayStart.plus({ days: 1 });
        const stop = event.stop && event.stop > event.start ? event.stop : event.start;
        const startsBefore = event.start < dayStart;
        const endsAfter = stop > dayEnd;
        if (startsBefore && endsAfter) {
            return this.texts.continues;
        }
        if (startsBefore) {
            return `${this.texts.endsAt} ${stop.toFormat("HH:mm")}`;
        }
        if (endsAfter) {
            return `${event.start.toFormat("HH:mm")} → ${stop.toFormat("LLL d")}`;
        }
        return event.timeLabel;
    }

    /**
     * 月视图: 跨天事件的横条, 按周行和列定位
     */
    get monthBars() {
        return layoutMonthBars(this.events, this.monthCells, 2).map((bar) => ({
            ...bar,
            key: `${bar.event.id}:${bar.row}`,
            style: `grid-row:${bar.row + 1};grid-column:${bar.startCol + 1} / ${bar.endCol + 2};margin-top:${38 + bar.lane * 16}px;--m_cal_color:${bar.event.color}`,
        }));
    }

    /** 时间轴: 选中日期的全天事件 */
    get allDayEvents() {
        return this.agenda.filter((event) => event.allDay);
    }

    /**
     * 时间轴: 选中日期的定时事件, 带位置样式. 拖动中的事件使用预览的位置
     */
    get blocks() {
        const drag = this.state.drag;
        return layoutTimedEvents(this.agenda, this.state.selected).map((block) => {
            let { top, height } = block;
            if (drag && drag.active && drag.id === block.event.id) {
                if (drag.mode === "move") {
                    top += (drag.delta / 60) * HOUR_HEIGHT;
                } else {
                    height = Math.max(height + (drag.delta / 60) * HOUR_HEIGHT, MIN_BLOCK_HEIGHT);
                }
            }
            return {
                ...block,
                style: `top:${top}px;height:${height}px;left:${block.left}%;width:${block.width}%;--m_cal_color:${block.event.color}`,
            };
        });
    }

    get title() {
        if (this.state.mode === "day") {
            return this.state.selected.toFormat("ccc, LLL d, yyyy");
        }
        if (this.state.mode === "week") {
            const { start, end } = weekRange(this.state.selected);
            const last = end.minus({ days: 1 });
            return start.month === last.month
                ? `${start.toFormat("LLL d")} – ${last.toFormat("d, yyyy")}`
                : `${start.toFormat("LLL d")} – ${last.toFormat("LLL d, yyyy")}`;
        }
        return this.state.selected.toFormat("LLLL yyyy");
    }

    get selectedTitle() {
        return this.state.selected.toFormat("cccc, LLL d");
    }

    get monthCells() {
        return this.cellsWithDots(buildMonthCells(this.state.selected, luxon.DateTime.local()));
    }

    get weekCells() {
        return this.cellsWithDots(buildWeekCells(this.state.selected, luxon.DateTime.local(), this.state.selected));
    }

    /** 格子上的圆点: 单日事件; 跨天事件画成横条 */
    cellsWithDots(cells) {
        const byDay = this.byDay;
        const selectedKey = this.selectedKey;
        return cells.map((cell) => {
            const events = (byDay.get(cell.key) || []).filter((event) => !isMultiDay(event));
            return {
                ...cell,
                dots: events.slice(0, 3).map((event) => event.color),
                isSelected: cell.key === selectedKey,
            };
        });
    }

    /** 切换到另一天, 并重新查询 (范围变化时) */
    selectDay(day) {
        this.state.selected = day.startOf("day");
        return this.load(this.props);
    }

    onNav(ev) {
        const direction = Number(ev.currentTarget.dataset.dir);
        const selected = this.state.selected;
        if (this.state.mode === "day") {
            return this.selectDay(selected.plus({ days: direction }));
        }
        if (this.state.mode === "week") {
            return this.selectDay(selected.plus({ weeks: direction }));
        }
        // month: keep the same day of the month when possible
        const month = selected.startOf("month").plus({ months: direction });
        return this.selectDay(month.set({ day: Math.min(selected.day, month.daysInMonth) }));
    }

    onToday() {
        return this.selectDay(luxon.DateTime.local());
    }

    onSelectDay(ev) {
        return this.selectDay(luxon.DateTime.fromISO(ev.currentTarget.dataset.day));
    }

    onMode(ev) {
        this.state.mode = ev.currentTarget.dataset.mode;
        return this.load(this.props);
    }

    onRowClick(ev) {
        this.props.onSelect(Number(ev.currentTarget.dataset.id));
    }

    onBlockClick(ev) {
        // a drag ends with a click on the same block: it must not open the record
        if (this.justDragged) {
            this.justDragged = false;
            return;
        }
        this.props.onSelect(Number(ev.currentTarget.dataset.id));
    }

    /* ---- moving and resizing timed events ---- */

    /**
     * 按下事件块: 长按后开始拖动; 在长按前上下滑动则视为滚动时间轴
     */
    onBlockPointerDown(ev) {
        if (!this.canDrag || ev.button > 0) {
            return;
        }
        this.beginDrag(Number(ev.currentTarget.dataset.id), "move", ev, false);
    }

    /** 按下底部把手: 立即开始调整时长 */
    onResizePointerDown(ev) {
        if (!this.canResize || ev.button > 0) {
            return;
        }
        ev.stopPropagation();
        this.beginDrag(Number(ev.currentTarget.dataset.id), "resize", ev, true);
    }

    beginDrag(id, mode, ev, immediate) {
        this.endDrag();
        this.dragContext = { startX: ev.clientX, startY: ev.clientY, id, mode };
        this.state.drag = { id, mode, delta: 0, active: immediate, moved: false };
        window.addEventListener("pointermove", this.onPointerMove);
        window.addEventListener("pointerup", this.onPointerUp);
        window.addEventListener("pointercancel", this.onPointerUp);
        if (!immediate) {
            this.timer = setTimeout(() => {
                this.timer = null;
                if (this.state.drag) {
                    this.state.drag.active = true;
                }
            }, LONG_PRESS_MS);
        }
    }

    onPointerMove = (ev) => {
        const drag = this.state.drag;
        const context = this.dragContext;
        if (!drag || !context) {
            return;
        }
        const dx = ev.clientX - context.startX;
        const dy = ev.clientY - context.startY;
        if (!drag.active) {
            // the finger moved before the long press: this is a scroll, not a drag
            if (Math.abs(dx) > SCROLL_TOLERANCE || Math.abs(dy) > SCROLL_TOLERANCE) {
                this.endDrag();
            }
            return;
        }
        ev.preventDefault();
        drag.moved = true;
        drag.delta = snapMinutes((dy / HOUR_HEIGHT) * 60);
    };

    onPointerUp = () => {
        const drag = this.state.drag;
        this.endDrag();
        if (drag && drag.active && drag.moved && drag.delta !== 0) {
            this.justDragged = true;
            return this.commitDrag(drag);
        }
    };

    /** 结束拖动: 清理计时器和监听, 不保存 */
    endDrag() {
        if (this.timer) {
            clearTimeout(this.timer);
            this.timer = null;
        }
        window.removeEventListener("pointermove", this.onPointerMove);
        window.removeEventListener("pointerup", this.onPointerUp);
        window.removeEventListener("pointercancel", this.onPointerUp);
        this.dragContext = null;
        this.state.drag = null;
    }

    /** 保存新的时间: 开始时间 (移动) 与结束时间 (移动或调整时长) */
    async commitDrag(drag) {
        const record = this.state.records.find((r) => r.id === drag.id);
        const event = record && this.toEvent(record);
        if (!event) {
            return;
        }
        const minutes = drag.delta;
        const values = {};
        if (drag.mode === "move") {
            values[this.dateStart] = serializeDateTime(event.start.plus({ minutes }));
            if (this.dateStop) {
                values[this.dateStop] = serializeDateTime(event.stop.plus({ minutes }));
            }
        } else {
            const stop = event.stop.plus({ minutes });
            // the event keeps at least one snap step
            const minStop = event.start.plus({ minutes: SNAP_MINUTES });
            values[this.dateStop] = serializeDateTime(stop < minStop ? minStop : stop);
        }
        try {
            await this.orm.write(this.props.resModel, [drag.id], values, { context: this.props.context || {} });
        } catch (error) {
            notify(this.notification, error?.data?.message || error?.message || this.texts.saveFailed, { type: "danger" });
        }
        await this.load(this.props, true);
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
