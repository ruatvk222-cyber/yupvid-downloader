"""Tests for the API wrapper using pytest-httpx."""

from __future__ import annotations

import httpx
import pytest
from pytest_httpx import HTTPXMock

from yupvid_downloader.api import YupVidClient
from yupvid_downloader.errors import APIError, SessionExpiredError


@pytest.fixture
def client() -> httpx.AsyncClient:
    return httpx.AsyncClient(base_url="https://yupvid.com")


async def test_list_projects_items_envelope(
    httpx_mock: HTTPXMock, client: httpx.AsyncClient
) -> None:
    httpx_mock.add_response(
        url="https://yupvid.com/api/projects/list",
        json={"items": [{"id": "1", "title": "One"}, {"id": "2", "title": "Two"}]},
    )
    api = YupVidClient(client)
    projects = await api.list_projects()
    assert [p.id for p in projects] == ["1", "2"]


async def test_list_projects_falls_back_to_projects(
    httpx_mock: HTTPXMock, client: httpx.AsyncClient
) -> None:
    httpx_mock.add_response(url="https://yupvid.com/api/projects/list", status_code=404)
    httpx_mock.add_response(
        url="https://yupvid.com/api/projects",
        json=[{"id": "9", "title": "Nine"}],
    )
    api = YupVidClient(client)
    [project] = await api.list_projects()
    assert project.id == "9"


async def test_list_projects_session_expired(
    httpx_mock: HTTPXMock, client: httpx.AsyncClient
) -> None:
    httpx_mock.add_response(
        url="https://yupvid.com/api/projects/list",
        status_code=401,
        json={"error": "Authentication required."},
    )
    api = YupVidClient(client)
    with pytest.raises(SessionExpiredError):
        await api.list_projects()


async def test_list_projects_server_error(httpx_mock: HTTPXMock, client: httpx.AsyncClient) -> None:
    httpx_mock.add_response(
        url="https://yupvid.com/api/projects/list",
        status_code=500,
        json={"error": "Boom"},
    )
    api = YupVidClient(client)
    with pytest.raises(APIError) as excinfo:
        await api.list_projects()
    assert excinfo.value.status_code == 500
    assert "Boom" in str(excinfo.value)


async def test_get_download_info_json(httpx_mock: HTTPXMock, client: httpx.AsyncClient) -> None:
    httpx_mock.add_response(
        url="https://yupvid.com/api/projects/download?id=abc",
        json={"url": "https://cdn.yupvid.com/abc.mp4", "sizeBytes": 1024},
    )
    api = YupVidClient(client)
    info = await api.get_download_info("abc")
    assert info is not None
    assert info.url == "https://cdn.yupvid.com/abc.mp4"
    assert info.size_bytes == 1024


async def test_get_download_info_binary_returns_none(
    httpx_mock: HTTPXMock, client: httpx.AsyncClient
) -> None:
    httpx_mock.add_response(
        url="https://yupvid.com/api/projects/download?id=abc",
        content=b"\x00\x01\x02",
        headers={"content-type": "video/mp4"},
    )
    api = YupVidClient(client)
    info = await api.get_download_info("abc")
    assert info is None
