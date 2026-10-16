"""Build a client from the system parameters of the database.

``get_param(key, default=None)`` is any callable returning a stored parameter.
"""
from .client import DEFAULT_API_BASE, OpenAICompatibleClient
from .errors import LLMNotConfigured

PARAM_API_BASE = 'openai.api_base'
PARAM_API_KEY = 'openai.api_key'
PARAM_MODEL = 'openai.model'
PARAM_EMBEDDING_MODEL = 'openai.embedding_model'
PARAM_TRANSCRIPTION_MODEL = 'openai.transcription_model'


def client_from_params(get_param):
    api_key = get_param(PARAM_API_KEY)
    model = get_param(PARAM_MODEL)
    if not api_key or not model:
        raise LLMNotConfigured(
            f"The AI service is not configured. Set the system parameters {PARAM_API_KEY} and {PARAM_MODEL}."
        )
    return OpenAICompatibleClient(
        api_key=api_key,
        api_base=get_param(PARAM_API_BASE) or DEFAULT_API_BASE,
        model=model,
        embedding_model=get_param(PARAM_EMBEDDING_MODEL),
        transcription_model=get_param(PARAM_TRANSCRIPTION_MODEL),
    )
