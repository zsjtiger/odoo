class LLMError(Exception):
    """A request to the language model service failed."""

    def __init__(self, message, status_code=None):
        super().__init__(message)
        self.status_code = status_code


class LLMNotConfigured(LLMError):
    """The language model service is not configured (missing key or model)."""
