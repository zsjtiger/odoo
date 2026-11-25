/**
 * 移动端日历视图的纯函数: 月历格子、事件的解析与按天分组.
 * 不依赖组件, 便于单元测试. 日期使用 luxon (与字段组件相同, 由 web 提供全局对象).
 */

/** 月历格子的行数: 6 周, 保证任何月份都能放下 */
export const GRID_WEEKS = 6;

/** 一个事件最多展开到的天数, 防止异常数据生成过多格子 */
export const MAX_SPAN_DAYS = 42;

/** 事件颜色的调色板 (字段为整数时按序号取色) */
export const PALETTE = ["#017e84", "#e5484d", "#f5a524", "#46a758", "#3e63dd", "#8e4ec6", "#d6409f", "#64748b"];

/**
 * 以某个日期为准的月份的月历格子 (周一开始, 共 6 周)
 *
 * @param {DateTime} month 月内任意一天
 * @param {DateTime} today 今天, 用于标记
 * @returns {{ key: string, day: number, inMonth: boolean, isToday: boolean, date: DateTime }[]}
 */
export function buildMonthCells(month, today) {
    const first = month.startOf("month");
    const gridStart = first.startOf("week");
    const todayKey = today.toISODate();
    const cells = [];
    for (let i = 0; i < GRID_WEEKS * 7; i++) {
        const date = gridStart.plus({ days: i });
        cells.push({
            key: date.toISODate(),
            day: date.day,
            inMonth: date.month === first.month,
            isToday: date.toISODate() === todayKey,
            date,
        });
    }
    return cells;
}

/** 格子覆盖的日期范围: [起始, 结束), 结束为第 6 周之后的第一天 */
export function gridRange(month) {
    const gridStart = month.startOf("month").startOf("week");
    return { start: gridStart, end: gridStart.plus({ days: GRID_WEEKS * 7 }) };
}

/**
 * 把事件放到它覆盖的每一天上. 跨天事件出现在每一天, 不超过 MAX_SPAN_DAYS 天.
 *
 * @param {{ id: number, start: DateTime, stop: DateTime, allDay: boolean, title: string, color: string }[]} events
 * @returns {Map<string, typeof events>} 日期键 (YYYY-MM-DD) -> 当天的事件, 按开始时间排序
 */
export function groupEventsByDay(events) {
    const byDay = new Map();
    for (const event of events) {
        const first = event.start.startOf("day");
        const last = (event.stop && event.stop > event.start ? event.stop : event.start).startOf("day");
        const span = Math.min(Math.round(last.diff(first, "days").days), MAX_SPAN_DAYS - 1);
        for (let i = 0; i <= span; i++) {
            const key = first.plus({ days: i }).toISODate();
            if (!byDay.has(key)) {
                byDay.set(key, []);
            }
            byDay.get(key).push(event);
        }
    }
    for (const list of byDay.values()) {
        list.sort((a, b) => (a.allDay === b.allDay ? a.start - b.start : a.allDay ? -1 : 1));
    }
    return byDay;
}

/**
 * 事件颜色: 字符串按颜色值使用, 整数按调色板取色, 其他情况使用主题色
 *
 * @param {*} value 颜色字段的值
 * @returns {string}
 */
export function eventColor(value) {
    if (typeof value === "string" && /^#[0-9a-fA-F]{3,8}$/.test(value)) {
        return value;
    }
    if (typeof value === "number" && value >= 0) {
        return PALETTE[value % PALETTE.length];
    }
    return PALETTE[0];
}

/** 周视图覆盖的范围: 包含 date 的那一周 (周一开始), [起始, 结束) */
export function weekRange(date) {
    const start = date.startOf("week");
    return { start, end: start.plus({ days: 7 }) };
}

/**
 * 周视图顶部的 7 天格子
 *
 * @param {DateTime} date 包含在该周内的任意一天
 * @param {DateTime} today
 * @param {DateTime} selected 选中的日期
 */
export function buildWeekCells(date, today, selected) {
    const { start } = weekRange(date);
    const todayKey = today.toISODate();
    const selectedKey = selected.toISODate();
    return Array.from({ length: 7 }, (_, i) => {
        const day = start.plus({ days: i });
        return {
            key: day.toISODate(),
            day: day.day,
            weekday: day.toFormat("ccc"),
            isToday: day.toISODate() === todayKey,
            isSelected: day.toISODate() === selectedKey,
            date: day,
        };
    });
}

/**
 * 一天的时间线: 0-23 点的小时行, 每行列出开始于该小时的非全天事件
 *
 * @param {{ start: DateTime, allDay: boolean }[]} events 当天的事件
 * @returns {{ hour: number, label: string, events: typeof events }[]}
 */
export function hourRows(events) {
    const rows = Array.from({ length: 24 }, (_, hour) => ({
        hour,
        label: `${String(hour).padStart(2, "0")}:00`,
        events: [],
    }));
    for (const event of events) {
        if (!event.allDay) {
            rows[event.start.hour].events.push(event);
        }
    }
    return rows;
}
