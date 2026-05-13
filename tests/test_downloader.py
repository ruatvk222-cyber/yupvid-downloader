"""Tests for the bulk downloader."""

from __future__ import annotations

from pathlib import Path

import httpx
from pytest_httpx import HTTPXMock

from yupvid_downloader.api import YupVidClient
from yupvid_downloader.downloader import BulkDownloader, safe_filename
from yupvid_downloader.models import Project


def _make_project(**overrides: object) -> Project:
    return Project.model_validate({"id": "p1", "title": "Hello / World!", **overrides})


def test_safe_filename_strips_slashes() -> None:
    project = _make_project()
    name = safe_filename(project)
    assert "/" not in name
    assert name.endswith("__p1.mp4")
    assert "Hello" in name


async def test_download_streams_via_binary_endpoint(
    httpx_mock: HTTPXMock,
    tmp_output_dir: Path,
) -> None:
    payload = b"VIDEO_BYTES" * 100
    httpx_mock.add_response(
        url="https://yupvid.com/api/projects/download?id=p1",
        content=b"",
        headers={"content-type": "video/mp4"},
    )
    httpx_mock.add_response(
        url="https://yupvid.com/api/projects/download?id=p1",
        content=payload,
        headers={"content-type": "video/mp4", "content-length": str(len(payload))},
    )

    async with httpx.AsyncClient(base_url="https://yupvid.com") as http:
        api = YupVidClient(http)
        downloader = BulkDownloader(api, tmp_output_dir, concurrency=1, max_attempts=1)
        [result] = await downloader.download_many([_make_project()])

    assert result.ok
    assert result.path.exists()
    assert result.path.read_bytes() == payload
    assert result.bytes_written == len(payload)


async def test_download_follows_json_redirect_url(
    httpx_mock: HTTPXMock,
    tmp_output_dir: Path,
) -> None:
    payload = b"REDIRECTED" * 50
    httpx_mock.add_response(
        url="https://yupvid.com/api/projects/download?id=p1",
        json={"url": "https://cdn.yupvid.com/p1.mp4", "sizeBytes": len(payload)},
    )
    httpx_mock.add_response(
        url="https://cdn.yupvid.com/p1.mp4",
        content=payload,
        headers={"content-type": "video/mp4", "content-length": str(len(payload))},
    )

    async with httpx.AsyncClient(base_url="https://yupvid.com") as http:
        api = YupVidClient(http)
        downloader = BulkDownloader(api, tmp_output_dir, concurrency=2, max_attempts=1)
        [result] = await downloader.download_many([_make_project()])

    assert result.ok
    assert result.path.read_bytes() == payload


async def test_download_skips_existing(
    httpx_mock: HTTPXMock,
    tmp_output_dir: Path,
) -> None:
    project = _make_project()
    existing = tmp_output_dir / safe_filename(project)
    existing.write_bytes(b"ALREADY_DOWNLOADED")

    async with httpx.AsyncClient(base_url="https://yupvid.com") as http:
        api = YupVidClient(http)
        downloader = BulkDownloader(api, tmp_output_dir, concurrency=1, max_attempts=1)
        [result] = await downloader.download_many([project])

    assert result.skipped
    assert result.path == existing
    assert existing.read_bytes() == b"ALREADY_DOWNLOADED"
    # No HTTP calls should have been recorded.
    assert httpx_mock.get_requests() == []


async def test_download_error_recorded_per_project(
    httpx_mock: HTTPXMock,
    tmp_output_dir: Path,
) -> None:
    httpx_mock.add_response(
        url="https://yupvid.com/api/projects/download?id=p1",
        status_code=500,
        json={"error": "boom"},
        is_reusable=True,
    )

    async with httpx.AsyncClient(base_url="https://yupvid.com") as http:
        api = YupVidClient(http)
        downloader = BulkDownloader(api, tmp_output_dir, concurrency=1, max_attempts=2)
        [result] = await downloader.download_many([_make_project()])

    assert not result.ok
    assert result.error is not None
    assert "boom" in result.error or "500" in result.error
