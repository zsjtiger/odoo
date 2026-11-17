import { describe, expect, test } from "@odoo/hoot";
import { MobileRecord } from "@mobile_web/views/record";
import { lineCommands } from "@mobile_web/views/record_model";

describe.current.tags("mobile");

const LINE_FIELDS = {
    name: { type: "char" },
    quantity: { type: "float" },
    partner_id: { type: "many2one", relation: "res.partner" },
};

test("lines are sent as create, update and delete commands", () => {
    const commands = lineCommands(
        LINE_FIELDS,
        [1, 2, 3],
        [
            [1, "A"],
            [2, "B"],
            [-1, "New line"],
        ],
        {
            1: { quantity: 5 },
            [-1]: { name: "New", partner_id: [7, "Partner"] },
        }
    );
    expect(commands).toEqual([
        [2, 3],
        [1, 1, { quantity: 5 }],
        [0, 0, { name: "New", partner_id: 7 }],
    ]);
});

test("an untouched existing line produces no command", () => {
    expect(lineCommands(LINE_FIELDS, [1], [[1, "A"]], {})).toEqual([]);
});

test("a new untouched line is still created", () => {
    expect(lineCommands(LINE_FIELDS, [], [[-1, "New line"]], {})).toEqual([[0, 0, {}]]);
});

test("setLines keeps the commands in the record changes until nothing is left", () => {
    const record = new MobileRecord({ lines: { type: "one2many", relation: "x" } }, 5, {
        lines: [[1, "A"]],
    });
    record.setLines("lines", [[1, "A"], [-1, "New line"]], {}, [[0, 0, {}]]);
    expect(record.changes.lines).toEqual([[0, 0, {}]]);
    expect(record.isDirty).toBe(true);
    record.setLines("lines", [[1, "A"]], {}, []);
    expect(record.changes.lines).toBe(undefined);
    expect(record.isDirty).toBe(false);
});

test("the original lines stay available to compute deletions", () => {
    const record = new MobileRecord({ lines: { type: "one2many", relation: "x" } }, 5, {
        lines: [[1, "A"]],
    });
    record.setLines("lines", [], {}, [[2, 1]]);
    expect(record.original.lines).toEqual([[1, "A"]]);
});
