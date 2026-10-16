import { describe, expect, test } from "@odoo/hoot";
import { patchTranslations } from "@web/../tests/_framework/translation_test_helpers";
import {
    defaultApprover,
    fromBpmnXml,
    approverOfLaneName,
    laneNameOf,
    toBpmnXml,
    validateModel,
} from "@snow_workflow/designer/bpmn_model";

describe.current.tags("headless");

// 校验信息是 _t 的惰性字符串, 测试中需要先加载翻译
patchTranslations({});

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
    noEnd.flows = noEnd.flows.filter((f) => f.target !== "e1");
    expect(validateModel(noEnd).some((e) => e.includes("end event"))).toBe(true);
    const twoStarts = model();
    twoStarts.nodes.push({ id: "s2", type: "start", name: "", x: 0, y: 0, approver: { type: "submitter", users: [], script: "" } });
    expect(validateModel(twoStarts).some((e) => e.includes("exactly one start"))).toBe(true);
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

test("an element the designer does not support is reported when the diagram is loaded", () => {
    const xml = toBpmnXml(model()).replace(
        "</bpmn:process>",
        '<bpmn:intermediateCatchEvent id="wait1"/></bpmn:process>'
    );
    const loaded = fromBpmnXml(xml);
    expect(loaded.unsupported).toEqual(["intermediateCatchEvent"]);
    expect(validateModel(loaded, loaded.unsupported).some((e) => e.includes("intermediateCatchEvent"))).toBe(true);
});

/** 排他网关: 一个条件分支 + 默认分支 */
function gatewayModel() {
    return {
        processId: "main_process",
        nodes: [
            { id: "s1", type: "start", name: "", x: 0, y: 0, approver: defaultApprover() },
            { id: "gw", type: "exclusive", name: "Amount", x: 100, y: 0, defaultFlow: "f_no", approver: defaultApprover() },
            { id: "e1", type: "end", name: "", x: 200, y: 0, approver: defaultApprover() },
            { id: "e2", type: "end", name: "", x: 200, y: 80, approver: defaultApprover() },
        ],
        flows: [
            { id: "f0", source: "s1", target: "gw", condition: "" },
            { id: "f_yes", source: "gw", target: "e1", condition: "amount > 100" },
            { id: "f_no", source: "gw", target: "e2", condition: "" },
        ],
    };
}

test("gateway conditions and the default flow survive the XML round trip", () => {
    const xml = toBpmnXml(gatewayModel());
    expect(xml.includes('default="f_no"')).toBe(true);
    expect(xml.includes("<bpmn:conditionExpression>amount &gt; 100</bpmn:conditionExpression>")).toBe(true);
    const back = fromBpmnXml(xml);
    expect(back.nodes.find((n) => n.id === "gw").defaultFlow).toBe("f_no");
    expect(back.flows.find((f) => f.id === "f_yes").condition).toBe("amount > 100");
    expect(validateModel(back)).toEqual([]);
});

test("a gateway with several outgoing flows needs a default and conditions on the others", () => {
    const noDefault = gatewayModel();
    noDefault.nodes.find((n) => n.id === "gw").defaultFlow = "";
    expect(validateModel(noDefault).some((e) => e.includes("default flow"))).toBe(true);
    const noCondition = gatewayModel();
    noCondition.flows.find((f) => f.id === "f_yes").condition = "";
    expect(validateModel(noCondition).some((e) => e.includes("condition"))).toBe(true);
});

/** 服务任务: 计算一个表达式, 结果写入 total */
function serviceModel(operator) {
    return {
        processId: "main_process",
        nodes: [
            { id: "s1", type: "start", name: "", x: 0, y: 0, approver: defaultApprover() },
            { id: "svc", type: "service", name: "Compute", x: 100, y: 0, operator, approver: defaultApprover() },
            { id: "e1", type: "end", name: "", x: 300, y: 0, approver: defaultApprover() },
        ],
        flows: [
            { id: "f0", source: "s1", target: "svc", condition: "" },
            { id: "f1", source: "svc", target: "e1", condition: "" },
        ],
    };
}

test("a service task keeps its operation, parameters and result variable", () => {
    const operator = {
        name: "evaluate",
        parameters: [{ name: "value", expression: "amount * 2" }],
        resultVariable: "total",
    };
    const xml = toBpmnXml(serviceModel(operator));
    expect(xml.includes('name="serviceTaskOperator"')).toBe(true);
    const back = fromBpmnXml(xml);
    expect(back.unsupported).toEqual([]);
    expect(back.nodes.find((n) => n.id === "svc").operator).toEqual(operator);
    expect(validateModel(back)).toEqual([]);
});

test("a service task needs a known operation, a value for evaluate, and valid names", () => {
    expect(validateModel(serviceModel({ name: "unknown", parameters: [], resultVariable: "" })).length).toBe(1);
    expect(validateModel(serviceModel({ name: "evaluate", parameters: [], resultVariable: "" })).length).toBe(1);
    expect(validateModel(serviceModel({
        name: "evaluate",
        parameters: [{ name: "value", expression: "1" }],
        resultVariable: "not valid",
    })).length).toBe(1);
});

/** 子流程: 内部一个审批节点 */
function subprocessModel() {
    return {
        processId: "main_process",
        nodes: [
            { id: "s1", type: "start", name: "", x: 0, y: 0, approver: defaultApprover() },
            { id: "sub", type: "subprocess", name: "Review", x: 100, y: 0, approver: defaultApprover(),
              children: {
                  nodes: [
                      { id: "cs", type: "start", name: "", x: 10, y: 10, approver: defaultApprover() },
                      { id: "ct", type: "approve_execution", name: "Inner", x: 100, y: 10,
                        approver: { type: "users", users: [5], script: "" } },
                      { id: "ce", type: "end", name: "", x: 300, y: 10, approver: defaultApprover() },
                  ],
                  flows: [
                      { id: "cf1", source: "cs", target: "ct", condition: "" },
                      { id: "cf2", source: "ct", target: "ce", condition: "" },
                  ],
              } },
            { id: "e1", type: "end", name: "", x: 300, y: 0, approver: defaultApprover() },
        ],
        flows: [
            { id: "f0", source: "s1", target: "sub", condition: "" },
            { id: "f1", source: "sub", target: "e1", condition: "" },
        ],
    };
}

test("a subprocess keeps its inner flow, including approvals with their approvers", () => {
    const xml = toBpmnXml(subprocessModel());
    expect(xml.includes('<bpmn:subProcess id="sub"')).toBe(true);
    const back = fromBpmnXml(xml);
    expect(back.unsupported).toEqual([]);
    const sub = back.nodes.find((n) => n.id === "sub");
    expect(sub.children.nodes.map((n) => n.type)).toEqual(["start", "approve_execution", "end"]);
    expect(sub.children.nodes.find((n) => n.id === "ct").approver).toEqual({ type: "users", users: [5], script: "" });
    expect(validateModel(back)).toEqual([]);
});

test("the inside of a subprocess is validated like a process", () => {
    const broken = subprocessModel();
    broken.nodes.find((n) => n.id === "sub").children.flows = [{ id: "cf1", source: "cs", target: "ct", condition: "" }];
    const errors = validateModel(broken);
    expect(errors.some((e) => e.includes("Inner") && e.includes("outgoing"))).toBe(true);
});

test("an approval task that is not one of the approval types is not supported", () => {
    const xml = toBpmnXml(model()).replace('name="approve_execution"', 'name="unknown_task"');
    expect(fromBpmnXml(xml).unsupported).toEqual(["userTask (unknown_task)"]);
});

test("a node without incoming or outgoing flows is an error", () => {
    const lonely = model();
    lonely.nodes.push({ id: "x1", type: "approve_execution", name: "Lonely", x: 0, y: 0,
        approver: { type: "submitter", users: [], script: "" } });
    const errors = validateModel(lonely);
    expect(errors.some((e) => e.includes("Lonely") && e.includes("incoming"))).toBe(true);
    expect(errors.some((e) => e.includes("Lonely") && e.includes("outgoing"))).toBe(true);
});
