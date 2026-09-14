"""The backend's exception vocabulary.

Every failure a caller can act on is one of these. They carry a plain-language
reason because that reason is shown to the person in the chat window.
"""


class AtlasError(RuntimeError):
    """Base class. Always carries a human-readable reason."""

    status_code = 500

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class DatasourceError(AtlasError):
    """Anything that stops us reaching the habitat data."""

    status_code = 502


class QueryError(AtlasError):
    """A query we refused to run, or arguments that made no sense."""

    status_code = 400


class ConversationNotFound(AtlasError):
    """The referenced conversation has expired or never existed."""

    status_code = 404


class ModelError(AtlasError):
    """The language model refused, failed, or could not be reached.

    `kind` travels to the browser on the error event, so the interface can
    tell "the local model is not running" from "the cloud rejected the key"
    and offer the right way out of each.
    """

    status_code = 502

    def __init__(self, message: str, kind: str = "model", recoverable: bool = True) -> None:
        super().__init__(message)
        self.kind = kind
        self.recoverable = recoverable


class ConfigurationError(AtlasError):
    """The service is missing configuration it cannot run without."""

    status_code = 503
