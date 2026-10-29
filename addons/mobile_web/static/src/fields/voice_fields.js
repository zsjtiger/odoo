import { mobileFieldRegistry } from "@mobile_web/views/registries";
import { CharField, TextField } from "@mobile_web/fields/basic_fields";
import { makeVoiceField } from "@mobile_web/fields/voice/voice";

/**
 * Mobile text fields with a microphone button for voice input:
 *
 * <field name="name" widget="char_voice"/>
 * <field name="description" widget="text_voice"/>
 */
mobileFieldRegistry.add("char_voice", makeVoiceField(CharField));
mobileFieldRegistry.add("text_voice", makeVoiceField(TextField));
