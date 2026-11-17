/**
 * Preferred recording formats, the first one supported by the browser is used.
 */
const PREFERRED_MIMETYPES = ["audio/webm;codecs=opus", "audio/webm", "audio/mp4", "audio/ogg;codecs=opus"];
const DEFAULT_MIMETYPE = "audio/webm";

function pickMimetype() {
    return PREFERRED_MIMETYPES.find((mimetype) => MediaRecorder.isTypeSupported(mimetype));
}

/**
 * Records the microphone with MediaRecorder, for a one-shot transcription.
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
     * Asks for the microphone and starts recording.
     * Rejects when the microphone is not available or not allowed.
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
     * Stops recording.
     *
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

    /**
     * Stops recording and drops the audio.
     */
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
