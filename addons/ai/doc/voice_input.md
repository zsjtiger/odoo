# Voice input for text fields

Text fields can be filled by speech. A microphone button is shown next to the
field: a first click starts the recording, a second click stops it, and the
transcript is appended to the text already in the field.

The feature works in the web client and in the mobile web client
(`mobile_web`).

## Enabling it

Voice input needs a transcription model. It is configured with the system
parameters below (Settings > Technical > Parameters > System Parameters):

| Key | Value |
| --- | --- |
| `openai.api_key` | API key of the provider |
| `openai.transcription_model` | Speech-to-text model, e.g. `whisper-1` |
| `openai.api_base` | Optional. Base URL of an OpenAI-compatible service |

The microphone button is shown only when `openai.api_key` and
`openai.transcription_model` are both set. Without them, the field works as a
normal text field.

## Using it in a view

Use the `char_voice` widget for a char field and `text_voice` for a text field:

```xml
<form>
    <field name="name" widget="char_voice"/>
    <field name="description" widget="text_voice"/>
</form>
```

Both widgets keep the options and the behavior of the standard `char` and
`text` widgets. They are available in form views and in the mobile form views.

## Behavior

- The browser asks for microphone access the first time the button is clicked.
- While recording, the button is red and shows a stop icon.
- After the second click, the audio is sent to the server and the button shows
  a spinner until the transcript is returned.
- The transcript is added after the current text, with a space in between when
  needed. Existing text is kept.
- The transcription language is the language of the current user.
- The button is hidden on read-only fields.
- If the microphone is not available or the transcription fails, a notification
  is shown and the field is not changed.

## Supported formats and limits

- Audio formats: `webm`, `mp4`, `ogg`, `wav`, `mp3`, `mpeg` and `flac`. The
  browser chooses the format it records in; `webm` is used when supported.
- Maximum audio size: 25 MB per recording.
- The transcription is a one-shot request: the whole recording is sent once
  it is stopped. Live (streaming) transcription is not used by these widgets.

## Server side

- `POST /ai/transcription` (JSON-RPC) takes `audio_base64`, `mimetype` and an
  optional `language`, and returns `{'status': 'success', 'text': ...}`.
- `POST /ai/transcription/available` tells whether the transcription model is
  configured. The widgets call it when the field is displayed.

The routes require a logged-in user, like the other AI routes.

## Troubleshooting

- **No microphone button:** check that `openai.api_key` and
  `openai.transcription_model` are set, and reload the page.
- **"The microphone is not available":** allow microphone access in the browser.
  On mobile, the page must be served over HTTPS.
- **"Unsupported audio format" or "The audio is too long":** the browser recorded
  a format or a duration that the server does not accept. Record a shorter
  text.
- **"Transcription failed":** check the provider configuration and the server
  log for the error returned by the transcription service.
