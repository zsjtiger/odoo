"""Run one language model job and describe its outcome.

A job is asked for asynchronously: it is stored, executed later by a worker,
and its outcome is handed back to the caller. ``job_outcome`` gives the outcome
in the shape the completion callback already consumes:
``(llm_result, llm_error)``, where ``llm_result`` is ``False`` on failure.
"""
import base64

from .errors import LLMError

JOB_COMPLETION = 'completion'
JOB_EMBEDDINGS = 'embeddings'
JOB_TRANSCRIPTION = 'transcription'
JOB_KINDS = (JOB_COMPLETION, JOB_EMBEDDINGS, JOB_TRANSCRIPTION)


def run_job(client, kind, payload):
    """Execute a job and return its result as a plain dict.

    :raises LLMError: when the service fails or the job is not supported.
    """
    if kind == JOB_COMPLETION:
        message = client.chat_completion(
            payload.get('messages') or [],
            instructions=payload.get('instructions'),
            tools=payload.get('tools'),
            options=payload.get('options'),
        )
        return {'result': message}
    if kind == JOB_EMBEDDINGS:
        return {'embeddings': client.embeddings(payload.get('input') or [], model=payload.get('model'))}
    if kind == JOB_TRANSCRIPTION:
        audio = base64.b64decode(payload['audio'])
        text = client.transcribe(
            audio,
            mimetype=payload.get('mimetype') or 'audio/mp3',
            language=payload.get('language'),
            model=payload.get('model'),
            response_format=payload.get('response_format') or 'json',
        )
        return {'text': text}
    raise LLMError(f"Unsupported job kind: {kind}")


def job_outcome(client, kind, payload):
    """Return ``(llm_result, llm_error)`` for a job, never raising for service errors."""
    try:
        return run_job(client, kind, payload), None
    except LLMError as e:
        return False, str(e)
