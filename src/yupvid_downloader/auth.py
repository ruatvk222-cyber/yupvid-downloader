"""Authentication helpers for YupVid.

Two flows are supported:

1. **Email + password** — calls ``POST /api/auth/login`` and captures the
   ``newsvideo_session`` cookie. The cookie is persisted to the OS keyring
   (via :mod:`keyring`) keyed by email so subsequent runs skip the login round
   trip until the session expires.
2. **Cookie import** — read an existing session from a Netscape ``cookies.txt``
   or JSON file (typically exported from the browser where you are already
   logged in). No password is needed.

Both flows produce a ready-to-use :class:`httpx.AsyncClient` with the session
cookie set on the ``yupvid.com`` domain.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
import keyring

from yupvid_downloader.config import SESSION_COOKIE_NAME, Settings
from yupvid_downloader.cookies import load_cookies
from yupvid_downloader.errors import AuthError, CookieFileError

logger = logging.getLogger(__name__)

KEYRING_SERVICE = "yupvid-downloader"


def _keyring_user(email: str) -> str:
    return f"session:{email.lower()}"


def save_session(email: str, cookie_value: str) -> None:
    """Persist a session cookie to the OS keyring."""
    keyring.set_password(KEYRING_SERVICE, _keyring_user(email), cookie_value)


def load_saved_session(email: str) -> str | None:
    """Return a previously saved session cookie, or ``None`` if none stored."""
    try:
        return keyring.get_password(KEYRING_SERVICE, _keyring_user(email))
    except keyring.errors.KeyringError as exc:
        logger.warning("keyring unavailable: %s", exc)
        return None


def clear_saved_session(email: str) -> None:
    """Delete the saved session cookie for ``email`` (no-op if absent)."""
    try:
        keyring.delete_password(KEYRING_SERVICE, _keyring_user(email))
    except keyring.errors.PasswordDeleteError:
        pass
    except keyring.errors.KeyringError as exc:
        logger.warning("keyring unavailable: %s", exc)


async def login_with_password(
    client: httpx.AsyncClient,
    email: str,
    password: str,
) -> str:
    """Authenticate against ``/api/auth/login`` and return the session cookie value.

    On success the cookie is also attached to ``client.cookies`` so the same
    client can immediately make authenticated requests.

    Raises:
        AuthError: server rejected the credentials or returned an unexpected shape.
    """
    if not email or not password:
        raise AuthError("email and password are required")
    if len(password) < 8:
        # Surface the server-side validation rule client-side for a clearer error.
        raise AuthError("password must be at least 8 characters")

    response = await client.post(
        "/api/auth/login",
        json={"email": email, "password": password},
        headers={"Referer": str(client.base_url) + "/login"},
    )

    if response.status_code in (200, 201):
        cookie = response.cookies.get(SESSION_COOKIE_NAME)
        if not cookie:
            # Some Next.js deployments don't echo cookies in the JSON-decoded
            # ``response.cookies`` because of the Set-Cookie attributes. Fall back
            # to reading the raw header.
            cookie = _extract_session_from_headers(response.headers.get_list("set-cookie"))
        if not cookie:
            raise AuthError(
                "login succeeded but no session cookie was returned "
                f"(set-cookie={response.headers.get('set-cookie')!r})"
            )
        return cookie

    # Try to surface the server's error message verbatim.
    message = _extract_error_message(response) or response.reason_phrase
    if response.status_code in (400, 401, 403, 500):
        raise AuthError(f"login failed (HTTP {response.status_code}): {message}")
    raise AuthError(f"unexpected response from /api/auth/login: HTTP {response.status_code}")


def _extract_error_message(response: httpx.Response) -> str | None:
    try:
        payload = response.json()
    except ValueError:
        return None
    if isinstance(payload, dict):
        for key in ("error", "message", "detail"):
            value = payload.get(key)
            if isinstance(value, str):
                return value
    return None


def _extract_session_from_headers(set_cookie_headers: list[str]) -> str | None:
    for header in set_cookie_headers:
        if header.startswith(f"{SESSION_COOKIE_NAME}="):
            value = header.split(";", 1)[0]
            return value[len(SESSION_COOKIE_NAME) + 1 :]
    return None


def _client_with_cookies(
    settings: Settings,
    cookies: dict[str, str],
) -> httpx.AsyncClient:
    cookie_jar = httpx.Cookies()
    for name, value in cookies.items():
        cookie_jar.set(name, value, domain="yupvid.com", path="/")
    return httpx.AsyncClient(
        base_url=settings.base_url,
        cookies=cookie_jar,
        timeout=settings.timeout_s,
        headers={
            "User-Agent": settings.user_agent,
            "Accept": "application/json",
        },
        follow_redirects=True,
    )


def client_from_cookie_file(settings: Settings, path: Path) -> httpx.AsyncClient:
    """Build an authenticated client from a cookie file on disk."""
    cookies = load_cookies(path)
    if SESSION_COOKIE_NAME not in cookies:
        raise CookieFileError(
            f"cookie file {path} does not contain '{SESSION_COOKIE_NAME}'. "
            "Make sure you exported cookies while logged in to yupvid.com."
        )
    return _client_with_cookies(settings, cookies)


def client_from_session_cookie(settings: Settings, session_cookie: str) -> httpx.AsyncClient:
    """Build an authenticated client from a raw session cookie value."""
    return _client_with_cookies(settings, {SESSION_COOKIE_NAME: session_cookie})


@asynccontextmanager
async def authenticated_client(
    settings: Settings,
    *,
    email: str | None = None,
    password: str | None = None,
    cookies_file: Path | None = None,
    use_saved_session: bool = True,
) -> AsyncIterator[httpx.AsyncClient]:
    """Yield an authenticated :class:`httpx.AsyncClient`.

    Resolution order (first match wins):

    1. ``cookies_file`` argument or ``settings.cookies_file``.
    2. A previously-saved session cookie in the keyring for ``email`` (if
       ``use_saved_session`` is true).
    3. Live ``email`` + ``password`` login.
    """
    cookies_file = cookies_file or settings.cookies_file
    email = email or settings.email
    password = password or settings.password

    if cookies_file is not None:
        client = client_from_cookie_file(settings, cookies_file)
        try:
            yield client
        finally:
            await client.aclose()
        return

    if email and use_saved_session:
        saved = load_saved_session(email)
        if saved:
            client = client_from_session_cookie(settings, saved)
            try:
                yield client
            finally:
                await client.aclose()
            return

    if not email or not password:
        raise AuthError(
            "no authentication available — provide either a cookie file, or "
            "YUPVID_EMAIL + YUPVID_PASSWORD (or run `yupvid-dl login`)."
        )

    client = httpx.AsyncClient(
        base_url=settings.base_url,
        timeout=settings.timeout_s,
        headers={"User-Agent": settings.user_agent, "Accept": "application/json"},
        follow_redirects=True,
    )
    try:
        cookie = await login_with_password(client, email, password)
        save_session(email, cookie)
        # Ensure the cookie is set on the client for the yielded session too.
        client.cookies.set(SESSION_COOKIE_NAME, cookie, domain="yupvid.com", path="/")
        yield client
    finally:
        await client.aclose()
