"""Schwab API integration errors."""


class SchwabHttpError(Exception):
    """Raised when Schwab returns a non-success HTTP status."""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code
