import { _t } from "@web/core/data/l10n/translation";
import { registry } from "@web/core/framework/registry";
import { charField } from "@web/views/fields/text/char/char_field";
import { textField } from "@web/views/fields/text/text/text_field";
import { makeVoiceField } from "@ai/speech/voice_field";

/**
 * Text fields with a microphone button for voice input:
 *
 * <field name="name" widget="char_voice"/>
 * <field name="description" widget="text_voice"/>
 *
 * The base fields are imported, so that they are registered before these widgets.
 * The button is shown only when the transcription model is configured.
 */
const fieldRegistry = registry.category("fields");

for (const [name, field, label] of [
    ["char_voice", charField, _t("Char with voice input")],
    ["text_voice", textField, _t("Text with voice input")],
]) {
    fieldRegistry.add(name, {
        ...field,
        displayName: label,
        component: makeVoiceField(field.component),
    });
}
