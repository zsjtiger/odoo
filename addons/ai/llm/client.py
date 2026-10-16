"""OpenAI-compatible client: chat completions, embeddings, transcription and realtime sessions.

Any server that implements the OpenAI HTTP API can be used through ``api_base``.
"""
import requests

from .converters import from_openai_message, to_openai_messages, to_openai_tools
from .errors import LLMError

DEFAULT_API_BASE = 'https://api.openai.com/v1'


class OpenAICompatibleClient:

    def __init__(self, api_key, api_base=DEFAULT_API_BASE, model=None,
                 embedding_model=None, transcription_model=None, timeout=60):
        self.api_key = api_key
        self.api_base = (api_base or DEFAULT_API_BASE).rstrip('/')
        self.model = model
        self.embedding_model = embedding_model
        self.transcription_model = transcription_model
        self.timeout = timeout

    def _url(self, path):
        return f"{self.api_base}{path}"

    def _request(self, method, path, **kwargs):
        headers = {'Authorization': f'Bearer {self.api_key}'}
        try:
            response = requests.request(
                method, self._url(path), headers=headers, timeout=self.timeout, **kwargs,
            )
        except requests.RequestException as e:
            raise LLMError(f"The language model service is unreachable: {e}") from e
        if response.status_code >= 400:
            raise LLMError(
                f"The language model service returned {response.status_code}: {response.text[:200]}",
                status_code=response.status_code,
            )
        try:
            return response.json()
        except ValueError as e:
            raise LLMError("The language model service returned an invalid response") from e

    def chat_completion(self, messages, instructions=None, tools=None, options=None):
        """Return an AssistantMessage for the given conversation."""
        body = {
            'model': self.model,
            'messages': to_openai_messages(messages, instructions=instructions),
        }
        if tools:
            body['tools'] = to_openai_tools(tools)
        schema = (options or {}).get('schema')
        if schema:
            body['response_format'] = {
                'type': 'json_schema',
                'json_schema': {'name': 'response', 'schema': schema},
            }
        data = self._request('POST', '/chat/completions', json=body)
        try:
            message = data['choices'][0]['message']
        except (KeyError, IndexError, TypeError) as e:
            raise LLMError("The language model service returned no message") from e
        return from_openai_message(message, model=data.get('model'), usage=data.get('usage'))

    def embeddings(self, inputs, model=None):
        """Return one embedding vector per input string, in input order."""
        data = self._request('POST', '/embeddings', json={
            'model': model or self.embedding_model,
            'input': list(inputs),
        })
        try:
            items = sorted(data['data'], key=lambda item: item['index'])
            return [item['embedding'] for item in items]
        except (KeyError, TypeError) as e:
            raise LLMError("The language model service returned no embeddings") from e

    def transcribe(self, audio, mimetype='audio/mp3', language=None, model=None):
        """Return the text of an audio file."""
        extension = mimetype.split('/')[-1] or 'mp3'
        form = {'model': model or self.transcription_model}
        if language:
            form['language'] = language
        data = self._request(
            'POST', '/audio/transcriptions',
            files={'file': (f'audio.{extension}', audio, mimetype)},
            data=form,
        )
        try:
            return data['text']
        except (KeyError, TypeError) as e:
            raise LLMError("The language model service returned no transcription") from e

    def create_transcription_session(self, language=None, prompt=None, model=None):
        """Create a realtime transcription session. The returned ``client_secret`` is used by the browser."""
        transcription = {'model': model or self.transcription_model}
        if language:
            transcription['language'] = language
        if prompt:
            transcription['prompt'] = prompt
        return self._request('POST', '/realtime/transcription_sessions', json={
            'input_audio_transcription': transcription,
        })
