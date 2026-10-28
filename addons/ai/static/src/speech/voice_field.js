import { Component, onWillStart, t, useProps, useState, xml } from "@odoo/owl";
import { VoiceInputButton } from "@ai/speech/voice_input_button";
import { isTranscriptionAvailable } from "@ai/speech/speech_service";
import { standardFieldProps } from "@web/views/fields/standard_field_props";

/**
 * Wraps a text-like field widget with a microphone button. The transcript is
 * appended to the current value, so that the typed text is kept.
 *
 * @param {typeof Component} FieldComponent the field widget to wrap
 * @param {string} [wrapperClass] class of the wrapper of the field and the button
 * @returns {typeof Component}
 */
export function makeVoiceField(FieldComponent, wrapperClass = "o_voice_field") {
    return class VoiceField extends Component {
        static components = { FieldComponent, VoiceInputButton };
        static template = xml`
            <div t-att-class="this.wrapperClass">
                <div class="o_voice_field_input flex-grow-1 min-w-0">
                    <FieldComponent t-props="this.props"/>
                </div>
                <VoiceInputButton t-if="this.state.available and !this.props.readonly" onTranscript="this.onTranscript"/>
            </div>`;

        props = useProps({
            ...standardFieldProps,
            placeholder: t.string().optional(),
        });
        state = useState({ available: false });
        wrapperClass = `${wrapperClass} d-flex align-items-start`;

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
