import { user } from "@web/core/services/user";
import { rpc } from "@web/core/services/network/rpc";

let availability = null;

/**
 * Whether the transcription model is configured. The answer is requested once.
 *
 * @returns {Promise<boolean>}
 */
export function isTranscriptionAvailable() {
    availability ??= rpc("/ai/transcription/available", {}, { silent: true }).catch(() => false);
    return availability;
}

/**
 * @param {Blob} blob
 * @returns {Promise<string>} the base64 content, without the data URL prefix
 */
function toBase64(blob) {
    return new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = () => resolve(reader.result.split(",")[1]);
        reader.onerror = () => reject(reader.error);
        reader.readAsDataURL(blob);
    });
}

/**
 * Transcribes a recorded audio, in the language of the user.
 *
 * @param {Blob} blob
 * @param {string} mimetype
 * @returns {Promise<string>} the transcript
 */
export async function transcribeAudio(blob, mimetype) {
    const response = await rpc(
        "/ai/transcription",
        {
            audio_base64: await toBase64(blob),
            mimetype,
            language: user.lang?.replace("-", "_").split("_")[0],
        },
        { silent: true }
    );
    return response.text || "";
}
