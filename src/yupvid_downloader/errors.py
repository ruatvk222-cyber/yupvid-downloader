"""Exception types for yupvid-downloader."""

from __future__ import annotations


class YupVidError(Exception):
    """Base error for all yupvid-downloader failures."""


class AuthError(YupVidError):
    """Raised when login fails or the session cookie is invalid/expired."""


class SessionExpiredError(AuthError):
    """Raised mid-request when the server returns 401 after we believed we were authed."""


class APIError(YupVidError):
    """Raised when an API request returns an unexpected status code."""

    def __init__(self, status_code: int, message: str, *, endpoint: str | None = None) -> None:
        self.status_code = status_code
        self.endpoint = endpoint
        suffix = f" ({endpoint})" if endpoint else ""
        super().__init__(f"HTTP {status_code}{suffix}: {message}")


class DownloadError(YupVidError):
    """Raised when a video download fails after exhausting retries."""

    def __init__(self, project_id: str, message: str) -> None:
        self.project_id = project_id
        super().__init__(f"download failed for {project_id}: {message}")


class CookieFileError(YupVidError):
    """Raised when a cookie file cannot be parsed or is missing the session cookie."""
