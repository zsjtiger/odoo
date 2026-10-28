import { describe, expect, test } from "@odoo/hoot";
import { animationFrame, click } from "@odoo/hoot-dom";
import { defineModels, fields, models, mountView, onRpc, patchWithCleanup, webModels } from "@web/../tests/web_test_helpers";
import { defineAIModels } from "./ai_test_helpers";

describe.current.tags("desktop");

class Note extends models.Model {
    name = fields.Char();
    description = fields.Text();

    _records = [{ id: 1, name: "Hello", description: "" }];
    _views = {
        form: /* xml */ `
            <form>
                <field name="name" widget="char_voice"/>
                <field name="description" widget="text_voice"/>
            </form>`,
    };
}

defineModels({ ...webModels, Note });
defineAIModels();

class FakeMediaRecorder extends EventTarget {
    static isTypeSupported(mimetype) {
        return mimetype === "audio/webm";
    }

    constructor(_stream, options) {
        super();
        this.state = "inactive";
        this.mimeType = options?.mimeType || "audio/webm";
    }

    start() {
        this.state = "recording";
    }

    stop() {
        this.state = "inactive";
        const dataAvailable = new Event("dataavailable");
        dataAvailable.data = new Blob(["audio"], { type: this.mimeType });
        this.dispatchEvent(dataAvailable);
        this.dispatchEvent(new Event("stop"));
    }
}

function mockMicrophone() {
    patchWithCleanup(window, { MediaRecorder: FakeMediaRecorder });
    patchWithCleanup(navigator.mediaDevices, {
        getUserMedia: async () => ({ getTracks: () => [{ stop() {} }] }),
    });
}

test("the microphone button is shown only when the transcription is configured", async () => {
    onRpc("/ai/transcription/available", () => false);
    await mountView({ type: "form", resModel: "note", resId: 1 });
    expect(".o_voice_input_button").toHaveCount(0);
});

test("a recording is transcribed and appended to the text", async () => {
    mockMicrophone();
    onRpc("/ai/transcription/available", () => true);
    onRpc("/ai/transcription", ({ mimetype }) => {
        expect.step(mimetype);
        return { status: "success", text: "world" };
    });
    await mountView({ type: "form", resModel: "note", resId: 1 });

    const micButton = ".o_field_widget[name='name'] .o_voice_input_button";
    await click(micButton);
    await animationFrame();
    expect(".o_field_widget[name='name'] .o_voice_input_recording").toHaveCount(1);

    await click(micButton);
    await animationFrame();
    expect(".o_voice_input_recording").toHaveCount(0);
    expect.verifySteps(["audio/webm"]);
    expect(".o_field_widget[name='name'] input").toHaveValue("Hello world");
});
