import { describe, expect, test } from "@odoo/hoot";
import { click, queryAll } from "@odoo/hoot-dom";
import { animationFrame } from "@odoo/hoot-mock";
import { mountWithCleanup } from "@web/../tests/_framework/component_test_helpers";
import { onRpc } from "@web/../tests/web_test_helpers";
import { session } from "@web/boot/session";
import { DefinitionContent } from "@snow_workflow/fields/definition_content";
import { WorkflowWarning } from "@snow_workflow/fields/workflow_warning";
import { WorkflowProcess } from "@snow_workflow/fields/workflow_process";
import { ApprovalButtons } from "@snow_workflow/views/approval_buttons";

describe.current.tags("headless");

/** 与字段组件交互的最小记录对象 */
function recordOf({ data = {}, context = {}, resId = 1, resModel = "snow.workflow.definition", isInEdition = false } = {}) {
    return {
        data,
        fields: { content: { type: "text", trim: false }, name: { type: "char" } },
        context,
        resId,
        resModel,
        isInEdition,
        isFieldTranslatable: () => false,
        isNew: false,
        dirty: false,
        model: { load: async () => {} },
    };
}

function fieldProps(record, name = "content", readonly = false) {
    return { name, record, readonly, id: `field_${name}`, options: {} };
}

const savedSession = { ...session };
function setSession(values) {
    Object.assign(session, { enable_common_workflow: false, approval_models: [] }, values);
}

/** 字段组件的 value 读取器 (只读时截取的逻辑在此), 不挂载组件以免依赖编辑态的 DOM */
function readValue(record, readonly) {
    const getter = Object.getOwnPropertyDescriptor(DefinitionContent.prototype, "value").get;
    return getter.call({ props: { name: "content", record, readonly } });
}

describe("definition content", () => {
    test("a read-only definition shows only its first five lines", () => {
        const text = ["1", "2", "3", "4", "5", "6", "7"].join("\n");
        expect(readValue(recordOf({ data: { content: text } }), true)).toBe("1\n2\n3\n4\n5\n...");
    });

    test("a short definition is shown in full", () => {
        expect(readValue(recordOf({ data: { content: "a\nb" } }), true)).toBe("a\nb");
    });

    test("an editable definition is shown in full", () => {
        const text = ["1", "2", "3", "4", "5", "6", "7"].join("\n");
        expect(readValue(recordOf({ data: { content: text } }), false)).toBe(text);
    });
});

describe("workflow warning", () => {
    test("submitting without agreeing shows a message and does not submit", async () => {
        const calls = [];
        onRpc("snow.workflow.alert", "write_and_verify_data", () => calls.push(true));
        await mountWithCleanup(WorkflowWarning, {
            props: fieldProps(recordOf({ context: { show_check_box: true, confirm: { model: "snow.workflow.alert", method: "write_and_verify_data" } } }), "name"),
        });
        await click("#submit");
        await animationFrame();
        expect(queryAll(".modal .modal-body").some((el) => el.textContent.includes("You must click read and agree!"))).toBe(true);
        expect(calls.length).toBe(0);
    });
});

describe("approval buttons", () => {
    test("nothing is shown when the approval workflow is disabled", async () => {
        setSession({ enable_common_workflow: false, approval_models: ["res.partner"] });
        onRpc("snow.workflow.action", "get_status", () => [{ button_name: "Approve" }]);
        await mountWithCleanup(ApprovalButtons, { props: { record: recordOf({ resModel: "res.partner" }) } });
        await animationFrame();
        expect(queryAll(".o_snow_approval_buttons button").length).toBe(0);
        setSession(savedSession);
    });

    test("a read-only record of an approval model shows its available actions", async () => {
        setSession({ enable_common_workflow: true, approval_models: ["res.partner"] });
        onRpc("snow.workflow.action", "get_status", () => [{ button_name: "Approve" }, { button_name: "Reject" }]);
        await mountWithCleanup(ApprovalButtons, { props: { record: recordOf({ resModel: "res.partner" }) } });
        await animationFrame();
        expect(queryAll(".o_snow_approval_buttons button").map((el) => el.textContent)).toEqual(["Approve", "Reject"]);
        setSession(savedSession);
    });
});

describe("workflow process", () => {
    test("each step is a collapsible header and the first one is open", async () => {
        const steps = [
            { create_date: "", submitter: "Alice", approve_roadmap: [{ group_type: "", state: "pass", members: [{ actor: "Bob", state: "pass", create_date: "", comments: "ok" }] }] },
            { create_date: "", submitter: "Carol", approve_roadmap: [] },
        ];
        onRpc("snow.workflow.action", "get_process_json", () => JSON.stringify(steps));
        await mountWithCleanup(WorkflowProcess, { props: fieldProps(recordOf(), "content", true) });
        await animationFrame();
        const headers = queryAll(".adm-step-header");
        expect(headers[0].textContent.includes("Alice")).toBe(true);
        expect(headers[1].textContent.includes("Carol")).toBe(true);
        // 第一个环节展开, 其余折叠
        expect(queryAll(".snow-steps-content.snow_hide").length).toBe(1);
        expect(queryAll(".adm-step-header.snow_hide").length).toBe(1);
    });
});
