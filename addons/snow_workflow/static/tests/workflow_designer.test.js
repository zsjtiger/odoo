import { describe, expect, test } from "@odoo/hoot";
import {
    fromBpmnXml,
    approverOfLaneName,
    laneNameOf,
    toBpmnXml,
    validateModel,
} from "@snow_workflow/designer/bpmn_model";

describe.current.tags("headless");

function model() {
    return {
        processId: "flow_demo",
        nodes: [
            { id: "s1", type: "start", name: "", x: 60, y: 120, approver: { type: "submitter", users: [], script: "" } },
            { id: "t1", type: "approve_execution", name: "Manager", x: 200, y: 100,
              approver: { type: "users", users: [3, 7], script: "" } },
            { id: "t2", type: "group_approve_execution_and", name: "", x: 400, y: 100,
              approver: { type: "script", users: [], script: "script_users" } },
            { id: "e1", type: "end", name: "", x: 640, y: 120, approver: { type: "submitter", users: [], script: "" } },
        ],
        flows: [
            { id: "f1", source: "s1", target: "t1" },
            { id: "f2", source: "t1", target: "t2" },
            { id: "f3", source: "t2", target: "e1" },
        ],
    };
}

test("lane names are the python dictionaries the engine reads", () => {
    expect(laneNameOf({ type: "submitter", users: [], script: "" })).toBe("{'user': 'submitter'}");
    expect(laneNameOf({ type: "users", users: [3, 7], script: "" })).toBe("{'user': {'domain': [('id', 'in', [3, 7])]}}");
    expect(laneNameOf({ type: "script", users: [], script: "script_users" })).toBe("{'script': {'key': 'script_users'}}");
});

test("an approver survives the lane name round trip", () => {
    expect(approverOfLaneName(laneNameOf({ type: "users", users: [3, 7], script: "" }))).toEqual({
        type: "users", users: [3, 7], script: "",
    });
    expect(approverOfLaneName(laneNameOf({ type: "script", users: [], script: "script_users" }))).toEqual({
        type: "script", users: [], script: "script_users",
    });
    expect(approverOfLaneName("{'user': 'submitter'}").type).toBe("submitter");
});

test("the designed diagram can be read back with its positions and approvers", () => {
    const back = fromBpmnXml(toBpmnXml(model()));
    expect(back.processId).toBe("main_process");
    expect(back.nodes.map((n) => n.type)).toEqual(["start", "approve_execution", "group_approve_execution_and", "end"]);
    const task = back.nodes.find((n) => n.id === "t1");
    expect(task.x).toBe(200);
    expect(task.y).toBe(100);
    expect(task.approver).toEqual({ type: "users", users: [3, 7], script: "" });
    expect(back.flows.map((f) => [f.source, f.target])).toEqual([["s1", "t1"], ["t1", "t2"], ["t2", "e1"]]);
});

test("the XML names approval tasks by their type, as the engine expects", () => {
    const xml = toBpmnXml(model());
    expect(xml.includes('<bpmn:userTask id="t1" name="approve_execution">')).toBe(true);
    expect(xml.includes('name="group_approve_execution_and"')).toBe(true);
    expect(xml.includes('<bpmn:process id="flow_demo" isExecutable="true">')).toBe(true);
});

test("a diagram needs exactly one start and at least one end", () => {
    const noEnd = model();
    noEnd.nodes = noEnd.nodes.filter((n) => n.type !== "end");
    expect(validateModel(noEnd).length).toBe(1);
    const twoStarts = model();
    twoStarts.nodes.push({ id: "s2", type: "start", name: "", x: 0, y: 0, approver: { type: "submitter", users: [], script: "" } });
    expect(validateModel(twoStarts).length).toBe(1);
    expect(validateModel(model())).toEqual([]);
});

test("approvals need an approver and a valid script key", () => {
    const noUsers = model();
    noUsers.nodes[1].approver = { type: "users", users: [], script: "" };
    expect(validateModel(noUsers).length).toBe(1);
    const badKey = model();
    badKey.nodes[2].approver = { type: "script", users: [], script: "bad key!" };
    expect(validateModel(badKey).length).toBe(1);
});

test("special characters in names are escaped in the XML", () => {
    const withName = model();
    withName.nodes[1].name = 'A & "B" <C>';
    const xml = toBpmnXml(withName);
    expect(xml.includes("A &amp; &quot;B&quot; &lt;C&gt;")).toBe(true);
    expect(fromBpmnXml(xml).nodes[1].name).toBe('A & "B" <C>');
});
