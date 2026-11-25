import { describe, expect, test } from "@odoo/hoot";
import {
    buildMonthCells,
    buildWeekCells,
    eventColor,
    gridRange,
    groupEventsByDay,
    GRID_WEEKS,
    hourRows,
    MAX_SPAN_DAYS,
    PALETTE,
    weekRange,
} from "@mobile_web/views/calendar/calendar_utils";

describe.current.tags("mobile");

const { DateTime } = luxon;

test("month grid has 6 weeks and starts on a Monday", () => {
    const cells = buildMonthCells(DateTime.fromISO("2026-11-15"), DateTime.fromISO("2026-11-25"));
    expect(cells.length).toBe(GRID_WEEKS * 7);
    expect(cells[0].date.weekday).toBe(1);
    // 2026-11-01 is a Sunday: the grid starts on Monday 2026-10-26
    expect(cells[0].key).toBe("2026-10-26");
});

test("month grid marks today and the days outside the month", () => {
    const cells = buildMonthCells(DateTime.fromISO("2026-11-15"), DateTime.fromISO("2026-11-25"));
    expect(cells.filter((c) => c.isToday).map((c) => c.key)).toEqual(["2026-11-25"]);
    expect(cells.find((c) => c.key === "2026-10-30").inMonth).toBe(false);
    expect(cells.find((c) => c.key === "2026-11-30").inMonth).toBe(true);
});

test("grid range covers the whole grid", () => {
    const { start, end } = gridRange(DateTime.fromISO("2026-11-15"));
    expect(start.toISODate()).toBe("2026-10-26");
    expect(end.diff(start, "days").days).toBe(42);
});

test("an event lands on the day it starts", () => {
    const start = DateTime.fromISO("2026-11-25T09:00");
    const byDay = groupEventsByDay([{ id: 1, start, stop: start, allDay: false, title: "A" }]);
    expect([...byDay.keys()]).toEqual(["2026-11-25"]);
});

test("a multi-day event appears on every day it covers", () => {
    const event = {
        id: 2,
        start: DateTime.fromISO("2026-11-24"),
        stop: DateTime.fromISO("2026-11-26"),
        allDay: true,
        title: "B",
    };
    expect([...groupEventsByDay([event]).keys()]).toEqual(["2026-11-24", "2026-11-25", "2026-11-26"]);
});

test("a very long event is capped in the number of days", () => {
    const event = {
        id: 3,
        start: DateTime.fromISO("2026-01-01"),
        stop: DateTime.fromISO("2026-12-31"),
        allDay: true,
        title: "C",
    };
    expect(groupEventsByDay([event]).size).toBe(MAX_SPAN_DAYS);
});

test("events of a day are sorted with all-day events first, then by start time", () => {
    const day = DateTime.fromISO("2026-11-25");
    const timed = { id: 1, start: day.set({ hour: 9 }), stop: day.set({ hour: 10 }), allDay: false, title: "timed" };
    const allDay = { id: 2, start: day, stop: day, allDay: true, title: "all day" };
    const early = { id: 3, start: day.set({ hour: 8 }), stop: day.set({ hour: 8 }), allDay: false, title: "early" };
    const ids = groupEventsByDay([timed, allDay, early]).get("2026-11-25").map((e) => e.id);
    expect(ids).toEqual([2, 3, 1]);
});

test("event color: strings are used as they are, integers pick from the palette", () => {
    expect(eventColor("#e5484d")).toBe("#e5484d");
    expect(eventColor(2)).toBe(PALETTE[2]);
    expect(eventColor(undefined)).toBe(PALETTE[0]);
    expect(eventColor("not a color")).toBe(PALETTE[0]);
});

test("week cells are the seven days from Monday, with the selected and today flags", () => {
    const selected = DateTime.fromISO("2026-11-25");
    const cells = buildWeekCells(selected, DateTime.fromISO("2026-11-25"), selected);
    expect(cells.map((c) => c.key)).toEqual([
        "2026-11-23",
        "2026-11-24",
        "2026-11-25",
        "2026-11-26",
        "2026-11-27",
        "2026-11-28",
        "2026-11-29",
    ]);
    expect(cells.filter((c) => c.isSelected).map((c) => c.key)).toEqual(["2026-11-25"]);
    expect(cells.filter((c) => c.isToday).map((c) => c.key)).toEqual(["2026-11-25"]);
});

test("week range is Monday to the next Monday", () => {
    const { start, end } = weekRange(DateTime.fromISO("2026-11-25"));
    expect(start.toISODate()).toBe("2026-11-23");
    expect(end.toISODate()).toBe("2026-11-30");
});

test("hour rows put a timed event in its start hour and leave all-day events out", () => {
    const day = DateTime.fromISO("2026-11-25");
    const rows = hourRows([
        { id: 1, start: day.set({ hour: 6, minute: 30 }), allDay: false },
        { id: 2, start: day, allDay: true },
    ]);
    expect(rows.length).toBe(24);
    expect(rows[6].events.map((e) => e.id)).toEqual([1]);
    expect(rows.flatMap((r) => r.events).map((e) => e.id)).toEqual([1]);
});
