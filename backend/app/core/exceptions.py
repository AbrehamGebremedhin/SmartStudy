from typing import Any


class OutOfContextError(Exception):
    """Raised when a request references a grade/subject/unit not in the curriculum."""

    def __init__(self, message: str, valid_options: dict[str, Any] | None = None):
        super().__init__(message)
        self.message = message
        self.valid_options = valid_options or {}
