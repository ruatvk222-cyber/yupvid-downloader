"""Tests for the auth helpers."""

from __future__ import annotations

import httpx
import pytest
from pytest_httpx import HTTPXMock

from yupvid_downloader.auth import login_with_password
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
