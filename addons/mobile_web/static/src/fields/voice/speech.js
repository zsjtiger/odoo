import { rpc } from "@web/core/services/network/rpc";
import { user } from "@web/core/services/user";

/**
 * Recording and transcription for the voice input of the mobile fields. The
 * same route as the web client is used: the transcription model is configured
 * with the system parameters of ai.
 */

const PREFERRED_MIMETYPES = ["audio/webm;codecs=opus", "audio/webm", "audio/mp4", "audio/ogg;codecs=opus"];
const DEFAULT_MIMETYPE = "audio/webm";

function pickMimetype() {
    return PREFERRED_MIMETYPES.find((mimetype) => MediaRecorder.isTypeSupported(mimetype));
}

/**
 * Records the microphone with MediaRecorder.
 */
export class SpeechRecorder {
    /** @type {MediaRecorder | null} */
    recorder = null;
    /** @type {MediaStream | null} */
    stream = null;
    chunks = [];

    get isRecording() {
        return Boolean(this.recorder);
    }

    /**
     * Asks for the microphone and starts recording. Rejects when the microphone
     * is not available or not allowed.
     */
    async start() {
        this.stream = await navigator.mediaDevices.getUserMedia({ audio: true });
        const mimeType = pickMimetype();
        this.chunks = [];
        this.recorder = new MediaRecorder(this.stream, mimeType ? { mimeType } : undefined);
        this.recorder.addEventListener("dataavailable", (ev) => {
            if (ev.data.size) {
                this.chunks.push(ev.data);
            }
        });
        this.recorder.start();
    }

    /**
     * @returns {Promise<{ blob: Blob, mimetype: string }>} the audio and its format,
     *          without the codec parameters
     */
    stop() {
        return new Promise((resolve) => {
            const recorder = this.recorder;
            recorder.addEventListener(
                "stop",
                () => {
                    const type = recorder.mimeType || DEFAULT_MIMETYPE;
                    const blob = new Blob(this.chunks, { type });
                    this.cleanup();
                    resolve({ blob, mimetype: type.split(";")[0] });
                },
                { once: true }
            );
            recorder.stop();
        });
    }

    /** Stops recording and drops the audio. */
    cancel() {
        if (this.recorder?.state !== "inactive") {
            this.recorder?.stop();
        }
        this.cleanup();
    }

    cleanup() {
        this.stream?.getTracks().forEach((track) => track.stop());
        this.stream = null;
        this.recorder = null;
        this.chunks = [];
    }
}

/**
 * @returns {Promise<boolean>} whether the transcription model is configured
 */
export function isTranscriptionAvailable() {
    return rpc("/ai/transcription/available", {}, { silent: true }).catch(() => false);
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
 * @param {Blob} blob
 * @param {string} mimetype
 * @returns {Promise<string>} the transcript, in the language of the user
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
