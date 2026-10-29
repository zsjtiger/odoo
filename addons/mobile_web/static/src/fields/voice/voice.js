import { Component, onWillStart, onWillUnmount, proxy, t, useProps, xml } from "@odoo/owl";
import { _t } from "@web/core/data/l10n/translation";
import { useService } from "@web/core/utils/hooks";
import { fieldProps } from "@mobile_web/fields/field_utils";
import {
    SpeechRecorder,
    isTranscriptionAvailable,
    transcribeAudio,
} from "@mobile_web/fields/voice/speech";

/**
 * Microphone button: a first tap starts the recording, the second one stops it
 * and the transcript is given to `onTranscript`.
 */
export class VoiceInputButton extends Component {
    static template = xml`
        <button type="button" class="m_voice_button" t-att-class="{'m_voice_button_recording': this.state.recording}"
                t-att-disabled="this.state.busy" t-on-click="this.onClick" t-esc="this.label"/>
    `;

    props = useProps({
        onTranscript: t.function(),
    });

    setup() {
        this.notification = useService("notification");
        this.recorder = new SpeechRecorder();
        this.state = proxy({ recording: false, busy: false });
        onWillUnmount(() => this.recorder.cancel());
    }

    get label() {
        if (this.state.busy) {
            return _t("Transcribing...");
        }
        return this.state.recording ? _t("Stop") : _t("Voice");
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

/**
 * Wraps a mobile text field with the microphone button. The transcript is
 * appended to the current value, so that the typed text is kept.
 *
 * @param {typeof Component} FieldComponent the mobile field to wrap
 * @returns {typeof Component}
 */
export function makeVoiceField(FieldComponent) {
    return class VoiceField extends Component {
        static components = { FieldComponent, VoiceInputButton };
        static template = xml`
            <div class="m_voice_field">
                <div class="m_voice_field_input">
                    <FieldComponent t-props="this.props"/>
                </div>
                <VoiceInputButton t-if="this.state.available and !this.props.readonly" onTranscript="this.onTranscript"/>
            </div>
        `;

        props = useProps({
            ...fieldProps,
            placeholder: t.string().optional(),
        });
        state = proxy({ available: false });

        setup() {
            onWillStart(async () => {
                this.state.available = await isTranscriptionAvailable();
            });
        }

        onTranscript = (text) => {
            const current = this.props.record.data[this.props.name] || "";
            const separator = current && !/\s$/.test(current) ? " " : "";
            this.props.record.update({ [this.props.name]: `${current}${separator}${text}` });
        };
    };
}
