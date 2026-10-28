import { _t } from "@web/core/data/l10n/translation";
import { registry } from "@web/core/framework/registry";
import { makeVoiceField } from "@ai/speech/voice_field";

/**
 * Text fields with a microphone button for voice input:
 *
 * <field name="name" widget="char_voice"/>
 * <field name="description" widget="text_voice"/>
 *
 * The button is shown only when the transcription model is configured.
 */
const fieldRegistry = registry.category("fields");

for (const [name, label] of [
    ["char", _t("Char with voice input")],
    ["text", _t("Text with voice input")],
]) {
    // The mobile client loads these files too, without the desktop field widgets
    if (!fieldRegistry.contains(name)) {
        continue;
    }
    const field = fieldRegistry.get(name);
    fieldRegistry.add(`${name}_voice`, {
        ...field,
        displayName: label,
        component: makeVoiceField(field.component),
    });
}
