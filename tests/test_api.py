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


async def test_list_projects_single_page(httpx_mock: HTTPXMock, client: httpx.AsyncClient) -> None:
    httpx_mock.add_response(
        url="https://yupvid.com/api/projects?skip=0&take=50",
        json={
            "projects": [{"id": "1", "title": "One"}, {"id": "2", "title": "Two"}],
            "total": 2,
            "skip": 0,
            "take": 50,
            "hasMore": False,
        },
    )
    api = YupVidClient(client)
    projects = await api.list_projects()
    assert [p.id for p in projects] == ["1", "2"]


async def test_list_projects_paginates_until_has_more_false(
    httpx_mock: HTTPXMock, client: httpx.AsyncClient
) -> None:
    httpx_mock.add_response(
        url="https://yupvid.com/api/projects?skip=0&take=2",
        json={
            "projects": [{"id": "1"}, {"id": "2"}],
            "total": 3,
            "skip": 0,
            "take": 2,
            "hasMore": True,
        },
    )
    httpx_mock.add_response(
        url="https://yupvid.com/api/projects?skip=2&take=2",
        json={
            "projects": [{"id": "3"}],
            "total": 3,
            "skip": 2,
            "take": 2,
            "hasMore": False,
        },
    )
    api = YupVidClient(client)
    projects = await api.list_projects(page_size=2)
    assert [p.id for p in projects] == ["1", "2", "3"]


async def test_list_projects_empty(httpx_mock: HTTPXMock, client: httpx.AsyncClient) -> None:
    httpx_mock.add_response(
        url="https://yupvid.com/api/projects?skip=0&take=50",
        json={"projects": [], "total": 0, "skip": 0, "take": 10, "hasMore": False},
    )
    api = YupVidClient(client)
    assert await api.list_projects() == []


async def test_list_projects_session_expired(
    httpx_mock: HTTPXMock, client: httpx.AsyncClient
) -> None:
    httpx_mock.add_response(
        url="https://yupvid.com/api/projects?skip=0&take=50",
        status_code=401,
        json={"error": "Authentication required."},
    )
    api = YupVidClient(client)
    with pytest.raises(SessionExpiredError):
        await api.list_projects()


async def test_list_projects_server_error(httpx_mock: HTTPXMock, client: httpx.AsyncClient) -> None:
    httpx_mock.add_response(
        url="https://yupvid.com/api/projects?skip=0&take=50",
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
