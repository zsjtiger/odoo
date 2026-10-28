import { Component, onWillUnmount, proxy, t, useProps } from "@odoo/owl";
import { _t } from "@web/core/data/l10n/translation";
import { useService } from "@web/core/utils/hooks";
import { SpeechRecorder } from "@ai/speech/speech_recorder";
import { transcribeAudio } from "@ai/speech/speech_service";

/**
 * Microphone button: a first click starts recording, the second one stops it and
 * the transcript is given to `onTranscript`.
 */
export class VoiceInputButton extends Component {
    static template = "ai.VoiceInputButton";

    props = useProps({
        onTranscript: t.function(),
        disabled: t.boolean().optional(),
    });

    setup() {
        this.notification = useService("notification");
        this.recorder = new SpeechRecorder();
        this.state = proxy({ recording: false, busy: false });
        onWillUnmount(() => this.recorder.cancel());
    }

    get title() {
        return this.state.recording ? _t("Stop recording") : _t("Voice input");
    }

    async onClick() {
        if (this.state.busy) {
            return;
        }
        if (this.recorder.isRecording) {
            await this.stopAndTranscribe();
            return;
        }
        try {
            await this.recorder.start();
            this.state.recording = true;
        } catch {
            this.notification.add(_t("The microphone is not available."), { type: "danger" });
        }
    }

    async stopAndTranscribe() {
        const { blob, mimetype } = await this.recorder.stop();
        this.state.recording = false;
        this.state.busy = true;
        try {
            const text = (await transcribeAudio(blob, mimetype)).trim();
            if (text) {
                this.props.onTranscript(text);
            }
        } catch {
            this.notification.add(_t("Transcription failed."), { type: "danger" });
        } finally {
            this.state.busy = false;
        }
    }
}
