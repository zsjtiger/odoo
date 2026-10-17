"""Language model access for the AI module.

Everything in this package is independent of the Odoo ORM: the client speaks
the OpenAI HTTP API, and the jobs module only runs a job and reports its outcome.
"""
from .client import DEFAULT_API_BASE, OpenAICompatibleClient
from .config import client_from_params
from .errors import LLMError, LLMNotConfigured
from .jobs import JOB_COMPLETION, JOB_EMBEDDINGS, JOB_KINDS, JOB_TRANSCRIPTION, job_outcome, run_job

__all__ = [
    'DEFAULT_API_BASE',
    'JOB_COMPLETION',
    'JOB_EMBEDDINGS',
    'JOB_KINDS',
    'JOB_TRANSCRIPTION',
    'LLMError',
    'LLMNotConfigured',
    'OpenAICompatibleClient',
    'client_from_params',
    'job_outcome',
    'run_job',
]
