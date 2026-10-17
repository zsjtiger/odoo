"""Convert between the AI module's message format and the OpenAI chat format."""
import base64
import json

from .errors import LLMError


def _inline_data_to_url(part):
    data = part['data']
    if isinstance(data, bytes):
        data = base64.b64encode(data).decode()
    return f"data:{part['mimetype']};base64,{data}"


def to_openai_messages(messages, instructions=None):
    out = []
    if instructions:
        out.append({'role': 'system', 'content': instructions})
    for message in messages:
        role = message['role']
        parts = message.get('content') or []
        if role == 'user':
            content = []
            tool_messages = []
            for part in parts:
                kind = part['type']
                if kind == 'text':
                    content.append({'type': 'text', 'text': part['text']})
                elif kind == 'inline_data':
                    content.append({'type': 'image_url', 'image_url': {'url': _inline_data_to_url(part)}})
                elif kind == 'tool_result':
                    tool_messages.append({
                        'role': 'tool',
                        'tool_call_id': part['tool_call_id'],
                        'content': json.dumps({'success': part['success'], 'result': part['result']}, default=str),
                    })
                else:
                    raise LLMError(f"Unsupported user content part: {kind}")
            if content:
                only_text = all(p['type'] == 'text' for p in content)
                out.append({
                    'role': 'user',
                    'content': '\n'.join(p['text'] for p in content) if only_text else content,
                })
            out.extend(tool_messages)
        elif role == 'assistant':
            texts = [p['text'] for p in parts if p['type'] == 'text']
            tool_calls = [
                {
                    'id': p['call_id'],
                    'type': 'function',
                    'function': {'name': p['name'], 'arguments': json.dumps(p.get('args') or {}, default=str)},
                }
                for p in parts if p['type'] == 'tool_call'
            ]
            assistant = {'role': 'assistant', 'content': '\n'.join(texts) or None}
            if tool_calls:
                assistant['tool_calls'] = tool_calls
            out.append(assistant)
        else:
            raise LLMError(f"Unsupported message role: {role}")
    return out


def to_openai_tools(tools):
    return [
        {
            'type': 'function',
            'function': {
                'name': tool['name'],
                'description': tool.get('instructions') or '',
                'parameters': tool.get('schema') or {'type': 'object', 'properties': {}},
            },
        }
        for tool in tools
    ]


def from_openai_message(message, model=None, usage=None):
    """Return an AssistantMessage built from an OpenAI chat completion message."""
    content = []
    if message.get('content'):
        content.append({'type': 'text', 'text': message['content']})
    for tool_call in message.get('tool_calls') or []:
        raw_arguments = tool_call['function'].get('arguments') or '{}'
        try:
            args = json.loads(raw_arguments)
        except json.JSONDecodeError as e:
            raise LLMError(f"Invalid arguments for tool call {tool_call['function'].get('name')!r}") from e
        content.append({
            'type': 'tool_call',
            'name': tool_call['function']['name'],
            'args': args,
            'call_id': tool_call['id'],
        })
    return {
        'role': 'assistant',
        'content': content,
        'provider_metadata': {'model': model, 'usage': usage or {}},
    }
