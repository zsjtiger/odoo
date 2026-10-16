# Part of Odoo. See LICENSE file for full copyright and licensing details.
import base64
import json
import unittest
from unittest.mock import MagicMock, patch

import requests

from odoo.addons.ai.llm import client as llm_client
from odoo.addons.ai.llm import config as llm_config
from odoo.addons.ai.llm import jobs as llm_jobs
from odoo.addons.ai.llm.converters import from_openai_message, to_openai_messages, to_openai_tools
from odoo.addons.ai.llm.errors import LLMError, LLMNotConfigured


def _response(status=200, json_data=None, text=''):
    response = MagicMock(status_code=status, text=text)
    if json_data is not None:
        response.json.return_value = json_data
    else:
        response.json.side_effect = ValueError('not json')
    return response


class TestConverters(unittest.TestCase):

    def test_instructions_become_a_system_message(self):
        messages = to_openai_messages([], instructions='Be brief.')
        self.assertEqual(messages, [{'role': 'system', 'content': 'Be brief.'}])

    def test_text_only_user_message_is_a_plain_string(self):
        messages = to_openai_messages([
            {'role': 'user', 'content': [{'type': 'text', 'text': 'Hello'}, {'type': 'text', 'text': 'world'}]},
        ])
        self.assertEqual(messages, [{'role': 'user', 'content': 'Hello\nworld'}])

    def test_inline_image_becomes_a_data_url(self):
        image = b'\x89PNG'
        messages = to_openai_messages([
            {'role': 'user', 'content': [
                {'type': 'text', 'text': 'What is this?'},
                {'type': 'inline_data', 'data': image, 'mimetype': 'image/png'},
            ]},
        ])
        content = messages[0]['content']
        self.assertEqual(content[0], {'type': 'text', 'text': 'What is this?'})
        self.assertEqual(content[1]['type'], 'image_url')
        self.assertEqual(
            content[1]['image_url']['url'],
            'data:image/png;base64,' + base64.b64encode(image).decode(),
        )

    def test_tool_results_become_tool_messages(self):
        messages = to_openai_messages([
            {'role': 'user', 'content': [{
                'type': 'tool_result', 'tool_name': 'get_time', 'tool_call_id': 'call_1',
                'result': [{'type': 'text', 'text': '12:00'}], 'success': True,
            }]},
        ])
        self.assertEqual(messages[0]['role'], 'tool')
        self.assertEqual(messages[0]['tool_call_id'], 'call_1')
        self.assertEqual(json.loads(messages[0]['content'])['success'], True)

    def test_assistant_tool_calls_are_serialised_as_json_arguments(self):
        messages = to_openai_messages([
            {'role': 'assistant', 'content': [
                {'type': 'text', 'text': 'Let me check.'},
                {'type': 'tool_call', 'name': 'get_time', 'args': {'tz': 'UTC'}, 'call_id': 'call_1'},
            ]},
        ])
        message = messages[0]
        self.assertEqual(message['content'], 'Let me check.')
        self.assertEqual(message['tool_calls'][0]['id'], 'call_1')
        self.assertEqual(json.loads(message['tool_calls'][0]['function']['arguments']), {'tz': 'UTC'})

    def test_unsupported_role_is_rejected(self):
        with self.assertRaises(LLMError):
            to_openai_messages([{'role': 'system', 'content': []}])

    def test_tools_map_to_function_definitions(self):
        tools = to_openai_tools([{'name': 'get_time', 'instructions': 'Gets the time', 'schema': {'type': 'object'}}])
        self.assertEqual(tools, [{
            'type': 'function',
            'function': {'name': 'get_time', 'description': 'Gets the time', 'parameters': {'type': 'object'}},
        }])

    def test_openai_message_with_text_becomes_an_assistant_message(self):
        message = from_openai_message({'role': 'assistant', 'content': 'Hi'}, model='m', usage={'total': 3})
        self.assertEqual(message['role'], 'assistant')
        self.assertEqual(message['content'], [{'type': 'text', 'text': 'Hi'}])
        self.assertEqual(message['provider_metadata'], {'model': 'm', 'usage': {'total': 3}})

    def test_openai_tool_calls_are_parsed(self):
        message = from_openai_message({
            'role': 'assistant', 'content': None,
            'tool_calls': [{'id': 'c1', 'type': 'function', 'function': {'name': 'f', 'arguments': '{"a": 1}'}}],
        })
        self.assertEqual(message['content'], [{'type': 'tool_call', 'name': 'f', 'args': {'a': 1}, 'call_id': 'c1'}])

    def test_invalid_tool_arguments_raise(self):
        with self.assertRaises(LLMError):
            from_openai_message({
                'role': 'assistant', 'content': None,
                'tool_calls': [{'id': 'c1', 'type': 'function', 'function': {'name': 'f', 'arguments': '{oops'}}],
            })


class TestClient(unittest.TestCase):

    def setUp(self):
        self.client = llm_client.OpenAICompatibleClient(
            api_key='secret', api_base='https://llm.example.com/v1/', model='chat-model',
            embedding_model='embed-model', transcription_model='stt-model',
        )

    def test_api_base_is_normalised(self):
        self.assertEqual(self.client.api_base, 'https://llm.example.com/v1')

    def test_chat_completion_sends_messages_tools_and_schema(self):
        completion = {
            'model': 'chat-model',
            'choices': [{'message': {'role': 'assistant', 'content': 'Done'}}],
            'usage': {'total_tokens': 5},
        }
        with patch.object(llm_client.requests, 'request', return_value=_response(json_data=completion)) as request:
            message = self.client.chat_completion(
                [{'role': 'user', 'content': [{'type': 'text', 'text': 'Hi'}]}],
                instructions='Be brief.',
                tools=[{'name': 'get_time', 'instructions': 'time', 'schema': {'type': 'object'}}],
                options={'schema': {'type': 'object'}},
            )
        method, url = request.call_args.args
        body = request.call_args.kwargs['json']
        self.assertEqual((method, url), ('POST', 'https://llm.example.com/v1/chat/completions'))
        self.assertEqual(request.call_args.kwargs['headers'], {'Authorization': 'Bearer secret'})
        self.assertEqual(body['model'], 'chat-model')
        self.assertEqual(body['messages'][0], {'role': 'system', 'content': 'Be brief.'})
        self.assertEqual(body['tools'][0]['function']['name'], 'get_time')
        self.assertEqual(body['response_format']['type'], 'json_schema')
        self.assertEqual(message['content'], [{'type': 'text', 'text': 'Done'}])
        self.assertEqual(message['provider_metadata']['usage'], {'total_tokens': 5})

    def test_http_error_raises_with_status(self):
        with patch.object(llm_client.requests, 'request', return_value=_response(401, text='bad key')):
            with self.assertRaises(LLMError) as ctx:
                self.client.chat_completion([])
        self.assertEqual(ctx.exception.status_code, 401)

    def test_unreachable_service_raises(self):
        with patch.object(llm_client.requests, 'request', side_effect=requests.ConnectionError('down')):
            with self.assertRaises(LLMError):
                self.client.chat_completion([])

    def test_response_without_choices_raises(self):
        with patch.object(llm_client.requests, 'request', return_value=_response(json_data={'choices': []})):
            with self.assertRaises(LLMError):
                self.client.chat_completion([])

    def test_non_json_response_raises(self):
        with patch.object(llm_client.requests, 'request', return_value=_response(text='<html>')):
            with self.assertRaises(LLMError):
                self.client.chat_completion([])

    def test_embeddings_are_returned_in_input_order(self):
        data = {'data': [
            {'index': 1, 'embedding': [0.2]},
            {'index': 0, 'embedding': [0.1]},
        ]}
        with patch.object(llm_client.requests, 'request', return_value=_response(json_data=data)) as request:
            vectors = self.client.embeddings(['a', 'b'])
        self.assertEqual(vectors, [[0.1], [0.2]])
        self.assertEqual(request.call_args.kwargs['json'], {'model': 'embed-model', 'input': ['a', 'b']})

    def test_transcription_uploads_the_audio(self):
        with patch.object(llm_client.requests, 'request', return_value=_response(json_data={'text': 'hello'})) as request:
            text = self.client.transcribe(b'audio-bytes', mimetype='audio/mp3', language='en')
        self.assertEqual(text, 'hello')
        kwargs = request.call_args.kwargs
        self.assertEqual(kwargs['data'], {'model': 'stt-model', 'language': 'en', 'response_format': 'json'})
        self.assertEqual(kwargs['files']['file'], ('audio.mp3', b'audio-bytes', 'audio/mp3'))

    def test_subtitle_transcription_returns_the_raw_text(self):
        with patch.object(llm_client.requests, 'request', return_value=_response(text='WEBVTT\n\n00:00.000 --> 00:01.000\nHi')) as request:
            text = self.client.transcribe(b'audio-bytes', mimetype='audio/mp3', response_format='vtt')
        self.assertEqual(text, 'WEBVTT\n\n00:00.000 --> 00:01.000\nHi')
        self.assertEqual(request.call_args.kwargs['data']['response_format'], 'vtt')

    def test_transcription_session_request(self):
        session = {'client_secret': {'value': 'ephemeral'}}
        with patch.object(llm_client.requests, 'request', return_value=_response(json_data=session)) as request:
            result = self.client.create_transcription_session(language='fr', prompt='Names: Odoo')
        self.assertEqual(result, session)
        self.assertEqual(request.call_args.args, ('POST', 'https://llm.example.com/v1/realtime/transcription_sessions'))
        self.assertEqual(request.call_args.kwargs['json'], {'input_audio_transcription': {
            'model': 'stt-model', 'language': 'fr', 'prompt': 'Names: Odoo',
        }})


class TestConfig(unittest.TestCase):

    def test_missing_key_or_model_is_not_configured(self):
        with self.assertRaises(LLMNotConfigured):
            llm_config.client_from_params(lambda key, default=None: None)
        with self.assertRaises(LLMNotConfigured):
            llm_config.client_from_params(lambda key, default=None: 'key' if key == 'openai.api_key' else None)

    def test_defaults_to_the_openai_api(self):
        params = {'openai.api_key': 'k', 'openai.model': 'm'}
        client = llm_config.client_from_params(lambda key, default=None: params.get(key))
        self.assertEqual(client.api_base, 'https://api.openai.com/v1')
        self.assertEqual(client.model, 'm')


class TestJobs(unittest.TestCase):

    def test_completion_job_returns_the_result(self):
        client = MagicMock()
        client.chat_completion.return_value = {'role': 'assistant', 'content': [], 'provider_metadata': {}}
        result = llm_jobs.run_job(client, llm_jobs.JOB_COMPLETION, {'messages': [], 'instructions': 'x'})
        self.assertEqual(result, {'result': client.chat_completion.return_value})
        client.chat_completion.assert_called_once_with([], instructions='x', tools=None, options=None)

    def test_transcription_job_decodes_the_audio(self):
        client = MagicMock()
        client.transcribe.return_value = 'hi'
        audio = base64.b64encode(b'raw').decode()
        result = llm_jobs.run_job(client, llm_jobs.JOB_TRANSCRIPTION, {'audio': audio, 'language': 'en'})
        self.assertEqual(result, {'text': 'hi'})
        self.assertEqual(client.transcribe.call_args.args[0], b'raw')

    def test_outcome_reports_failures_instead_of_raising(self):
        client = MagicMock()
        client.embeddings.side_effect = LLMError('service down')
        self.assertEqual(
            llm_jobs.job_outcome(client, llm_jobs.JOB_EMBEDDINGS, {'input': ['a']}),
            (False, 'service down'),
        )

    def test_outcome_on_success(self):
        client = MagicMock()
        client.embeddings.return_value = [[0.1]]
        llm_result, error = llm_jobs.job_outcome(client, llm_jobs.JOB_EMBEDDINGS, {'input': ['a']})
        self.assertIsNone(error)
        self.assertEqual(llm_result, {'embeddings': [[0.1]]})

    def test_unknown_job_kind_is_a_failure(self):
        self.assertEqual(llm_jobs.job_outcome(MagicMock(), 'unknown', {}), (False, 'Unsupported job kind: unknown'))
