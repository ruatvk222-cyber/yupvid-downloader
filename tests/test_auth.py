"""Tests for the auth helpers."""

from __future__ import annotations

import httpx
import keyring
import pytest
from pytest_httpx import HTTPXMock

from yupvid_downloader.auth import (
    KEYRING_SERVICE,
    load_saved_session,
    login_with_password,
    save_session,
)
from yupvid_downloader.errors import AuthError


async def test_login_with_password_success(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(
        url="https://yupvid.com/api/auth/login",
        method="POST",
        status_code=200,
        json={"ok": True},
        headers={"set-cookie": "newsvideo_session=COOKIEVALUE; Path=/; HttpOnly; SameSite=Lax"},
    )
    async with httpx.AsyncClient(base_url="https://yupvid.com") as client:
        cookie = await login_with_password(client, "user@example.com", "longpassword")
    assert cookie == "COOKIEVALUE"


async def test_login_with_password_invalid_credentials(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(
        url="https://yupvid.com/api/auth/login",
        method="POST",
        status_code=500,
        json={"error": "Invalid email or password."},
    )
    async with httpx.AsyncClient(base_url="https://yupvid.com") as client:
        with pytest.raises(AuthError, match="Invalid email or password"):
            await login_with_password(client, "user@example.com", "longpassword")


async def test_login_with_password_short_password_short_circuits() -> None:
    async with httpx.AsyncClient(base_url="https://yupvid.com") as client:
        with pytest.raises(AuthError, match="at least 8 characters"):
            await login_with_password(client, "user@example.com", "short")


async def test_login_with_password_missing_cookie(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(
        url="https://yupvid.com/api/auth/login",
        method="POST",
        status_code=200,
        json={"ok": True},
    )
    async with httpx.AsyncClient(base_url="https://yupvid.com") as client:
        with pytest.raises(AuthError, match="no session cookie"):
            await login_with_password(client, "user@example.com", "longpassword")


def test_save_session_returns_false_when_no_keyring_backend(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Headless environments without a keyring backend should warn, not crash."""

    def _raise(*_args: object, **_kwargs: object) -> None:
        raise keyring.errors.NoKeyringError("no backend in this env")

    monkeypatch.setattr(keyring, "set_password", _raise)
    assert save_session("user@example.com", "cookie-value") is False


def test_save_session_returns_true_when_keyring_works(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, str] = {}

    def _set(service: str, user: str, value: str) -> None:
        captured.update(service=service, user=user, value=value)

    monkeypatch.setattr(keyring, "set_password", _set)
    assert save_session("USER@example.com", "cookie-value") is True
    assert captured["service"] == KEYRING_SERVICE
    assert captured["user"] == "session:user@example.com"  # lowercased
    assert captured["value"] == "cookie-value"


def test_load_saved_session_returns_none_when_no_keyring_backend(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _raise(*_args: object, **_kwargs: object) -> None:
        raise keyring.errors.NoKeyringError("no backend")

    monkeypatch.setattr(keyring, "get_password", _raise)
    assert load_saved_session("user@example.com") is None
