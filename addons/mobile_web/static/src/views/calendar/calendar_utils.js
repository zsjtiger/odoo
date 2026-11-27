/**
 * 移动端日历视图的纯函数: 月历格子、事件的解析与按天分组.
 * 不依赖组件, 便于单元测试. 日期使用 luxon (与字段组件相同, 由 web 提供全局对象).
 */

/** 月历格子的行数: 6 周, 保证任何月份都能放下 */
export const GRID_WEEKS = 6;

/** 一个事件最多展开到的天数, 防止异常数据生成过多格子 */
export const MAX_SPAN_DAYS = 42;

import { paletteColor } from "@mobile_web/core/theme";

/**
 * 事件颜色的调色板 (字段为整数时按序号取色). 默认值与样式令牌中的 $calendar-palette 相同;
 * 实际颜色由主题提供 (--m-calendar-<n>)
 */
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
        return paletteColor("calendar", PALETTE, value);
    }
    return paletteColor("calendar", PALETTE, 0);
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

/** 时间轴: 一小时的高度 (px) 与拖拽吸附的分钟数 */
export const HOUR_HEIGHT = 56;
export const SNAP_MINUTES = 15;
/** 时长最短的块高度 (px), 很短的事件也能点到 */
export const MIN_BLOCK_HEIGHT = 26;

/**
 * 把一天的非全天事件排成时间轴上的块. 跨天事件只取当天的部分.
 * 同一时段重叠的事件分成若干列, 每列等宽并排 (与桌面端的日历相同).
 *
 * @param {{ id: number, start: DateTime, stop: DateTime, allDay: boolean }[]} events
 * @param {DateTime} day 当天 (任意时刻)
 * @returns {{ event: object, top: number, height: number, left: number, width: number }[]}
 */
export function layoutTimedEvents(events, day) {
    const dayStart = day.startOf("day");
    const dayEnd = dayStart.plus({ days: 1 });
    const items = events
        .filter((event) => !event.allDay && event.start < dayEnd && (event.stop ?? event.start) >= dayStart)
        .map((event) => {
            const start = event.start < dayStart ? dayStart : event.start;
            const stopRaw = event.stop && event.stop > event.start ? event.stop : start;
            const stop = stopRaw > dayEnd ? dayEnd : stopRaw;
            const startMin = start.diff(dayStart, "minutes").minutes;
            const endMin = Math.max(stop.diff(dayStart, "minutes").minutes, startMin + SNAP_MINUTES);
            return { event, startMin, endMin };
        })
        .sort((a, b) => a.startMin - b.startMin || b.endMin - a.endMin);

    const blocks = [];
    let cluster = [];
    let clusterEnd = -Infinity;
    const flush = () => {
        const columns = cluster.reduce((max, item) => Math.max(max, item.col + 1), 0);
        for (const item of cluster) {
            blocks.push({
                event: item.event,
                top: (item.startMin / 60) * HOUR_HEIGHT,
                height: Math.max(((item.endMin - item.startMin) / 60) * HOUR_HEIGHT, MIN_BLOCK_HEIGHT),
                left: (item.col / columns) * 100,
                width: (1 / columns) * 100,
            });
        }
        cluster = [];
    };
    for (const item of items) {
        if (item.startMin >= clusterEnd) {
            flush();
            clusterEnd = -Infinity;
        }
        // first column whose last event has ended before this one starts
        const columnEnds = [];
        for (const placed of cluster) {
            columnEnds[placed.col] = Math.max(columnEnds[placed.col] ?? -Infinity, placed.endMin);
        }
        let col = columnEnds.findIndex((end) => end <= item.startMin);
        if (col === -1) {
            col = columnEnds.length;
        }
        cluster.push({ ...item, col });
        clusterEnd = Math.max(clusterEnd, item.endMin);
    }
    flush();
    return blocks;
}

/** 把块的位置 (分钟) 吸附到 SNAP_MINUTES */
export function snapMinutes(minutes) {
    return Math.round(minutes / SNAP_MINUTES) * SNAP_MINUTES;
}

/** 事件是否跨越多天 (结束日期晚于开始日期) */
export function isMultiDay(event) {
    const stop = event.stop && event.stop > event.start ? event.stop : event.start;
    return stop.startOf("day") > event.start.startOf("day");
}

/**
 * 月视图中跨天事件的横条: 每一周一行, 每条横条按周内的列 (startCol..endCol) 占位.
 * 同一周内重叠的横条放在不同的行 (lane); 超过 maxLanes 的不画, 它们仍在事件列表中.
 *
 * @param {{ event: object, start: DateTime, stop: DateTime }[]} events
 * @param {{ date: DateTime }[]} cells 月历格子 (6 周 * 7 天)
 * @param {number} maxLanes
 * @returns {{ event: object, row: number, startCol: number, endCol: number, lane: number }[]}
 */
export function layoutMonthBars(events, cells, maxLanes = 2) {
    const first = cells[0].date.startOf("day");
    const indexOf = (dt) => Math.round(dt.startOf("day").diff(first, "days").days);
    const bars = [];
    for (const event of events) {
        if (!isMultiDay(event)) {
            continue;
        }
        const from = indexOf(event.start);
        const stop = event.stop && event.stop > event.start ? event.stop : event.start;
        const to = indexOf(stop);
        for (let row = 0; row < cells.length / 7; row++) {
            const rowStart = row * 7;
            const rowEnd = rowStart + 6;
            const a = Math.max(from, rowStart);
            const b = Math.min(to, rowEnd);
            if (a <= b) {
                bars.push({ event, row, startCol: a - rowStart, endCol: b - rowStart });
            }
        }
    }
    const result = [];
    for (let row = 0; row < cells.length / 7; row++) {
        const rowBars = bars
            .filter((bar) => bar.row === row)
            .sort((x, y) => x.startCol - y.startCol || y.endCol - x.endCol);
        const laneEnds = [];
        for (const bar of rowBars) {
            let lane = laneEnds.findIndex((end) => end < bar.startCol);
            if (lane === -1) {
                lane = laneEnds.length;
                laneEnds.push(bar.endCol);
            } else {
                laneEnds[lane] = bar.endCol;
            }
            if (lane < maxLanes) {
                result.push({ ...bar, lane });
            }
        }
    }
    return result;
}
