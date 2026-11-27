import { describe, expect, test } from "@odoo/hoot";
import { PAGE_SIZE, RecordCollection } from "@mobile_web/views/record_list";

describe.current.tags("mobile");

const FIELDS = { name: { type: "char" } };

/** 模拟服务端: 按 offset/limit 分页返回 rows, 并记录每次请求 */
function fakeModel(rows, { delay = null } = {}) {
    const calls = [];
    return {
        fields: FIELDS,
        calls,
        searchRecords({ offset, limit }) {
            calls.push({ offset, limit });
            const result = { records: rows.slice(offset, offset + limit), length: rows.length };
            return delay ? delay(calls.length).then(() => result) : Promise.resolve(result);
        },
    };
}

const rows = (n) => Array.from({ length: n }, (_, i) => ({ id: i + 1, name: `R${i + 1}` }));

test("reload loads the first page and the total", async () => {
    const model = fakeModel(rows(PAGE_SIZE + 5));
    const collection = new RecordCollection(model, ["name"]);
    await collection.reload([]);
    expect(collection.state.records.length).toBe(PAGE_SIZE);
    expect(collection.state.total).toBe(PAGE_SIZE + 5);
    expect(collection.state.loading).toBe(false);
    expect(model.calls[0].offset).toBe(0);
    expect(model.calls[0].limit).toBe(PAGE_SIZE);
});

test("loadMore appends the next page after the loaded records", async () => {
    const model = fakeModel(rows(PAGE_SIZE + 5));
    const collection = new RecordCollection(model, ["name"]);
    await collection.reload([]);
    await collection.loadMore();
    expect(collection.state.records.length).toBe(PAGE_SIZE + 5);
    expect(collection.state.records[PAGE_SIZE].resId).toBe(PAGE_SIZE + 1);
    expect(model.calls[1].offset).toBe(PAGE_SIZE);
});

test("loadMore does nothing once every record is loaded", async () => {
    const model = fakeModel(rows(3));
    const collection = new RecordCollection(model, ["name"]);
    await collection.reload([]);
    await collection.loadMore();
    expect(model.calls.length).toBe(1);
});

test("a stale response from an earlier reload is ignored", async () => {
    let release;
    const model = fakeModel(rows(3), {
        delay: (call) => (call === 1 ? new Promise((resolve) => (release = resolve)) : Promise.resolve()),
    });
    const collection = new RecordCollection(model, ["name"]);
    const first = collection.reload([{ id: 1 }]);
    await collection.reload([]);
    release();
    await first;
    expect(collection.state.records.length).toBe(3);
});

test("a failing request is kept in state.error", async () => {
    const error = new Error("boom");
    const model = { fields: FIELDS, searchRecords: () => Promise.reject(error) };
    const collection = new RecordCollection(model, ["name"]);
    await collection.reload([]);
    expect(collection.state.error).toBe(error);
    expect(collection.state.loading).toBe(false);
});

test("records keep their UI data converted from the server", async () => {
    const model = fakeModel([{ id: 2, name: "Ann", display_name: "Ann" }]);
    const collection = new RecordCollection(model, ["name"]);
    await collection.reload([]);
    expect(collection.state.records[0].resId).toBe(2);
    expect(collection.state.records[0].data.name).toBe("Ann");
});
