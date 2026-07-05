from typing import Optional


def format_error_details(exc: BaseException, *, context: Optional[str] = None) -> str:
    exc_type = type(exc).__name__
    message = str(exc).strip() or "No details available."
    if context:
        return f"{context} | {exc_type}: {message}"
    return f"{exc_type}: {message}"
