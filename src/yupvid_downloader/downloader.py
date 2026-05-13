"""Async bulk video downloader with retry + resume support."""

from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
from tenacity import (
    AsyncRetrying,
    RetryError,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from yupvid_downloader.api import YupVidClient
from yupvid_downloader.errors import APIError, DownloadError, SessionExpiredError
from yupvid_downloader.models import Project

logger = logging.getLogger(__name__)

# Called as ``on_progress(project_id, bytes_so_far, total_bytes_or_None)``.
ProgressCallback = Callable[[str, int, "int | None"], None]

_FILENAME_SAFE = re.compile(r"[^A-Za-z0-9._\- ]+")
_CONTENT_DISPOSITION_FILENAME = re.compile(
    r'filename\*?=(?:UTF-8\'\')?"?(?P<value>[^";]+)"?', re.IGNORECASE
)


@dataclass(slots=True)
class DownloadResult:
    project_id: str
    path: Path
    bytes_written: int
    skipped: bool = False
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None


def safe_filename(project: Project, *, suffix: str = ".mp4") -> str:
    """Build a stable, filesystem-safe filename for ``project``."""
    base = _FILENAME_SAFE.sub("_", project.display_title).strip("._ ")
    if not base:
        base = f"project-{project.id}"
    # Always suffix with the project id so duplicate titles never collide.
    return f"{base}__{project.id}{suffix}"


class BulkDownloader:
    """Drives concurrent downloads for a list of projects."""

    def __init__(
        self,
        client: YupVidClient,
        output_dir: Path,
        *,
        concurrency: int = 3,
        max_attempts: int = 4,
        chunk_size: int = 64 * 1024,
        on_progress: ProgressCallback | None = None,
    ) -> None:
        if concurrency < 1:
            raise ValueError("concurrency must be >= 1")
        if max_attempts < 1:
            raise ValueError("max_attempts must be >= 1")
        self._client = client
        self._output_dir = output_dir
        self._semaphore = asyncio.Semaphore(concurrency)
        self._max_attempts = max_attempts
        self._chunk_size = chunk_size
        self._on_progress = on_progress

    async def download_many(
        self, projects: Sequence[Project], *, overwrite: bool = False
    ) -> list[DownloadResult]:
        self._output_dir.mkdir(parents=True, exist_ok=True)
        tasks = [
            asyncio.create_task(self._download_one_guarded(project, overwrite=overwrite))
            for project in projects
        ]
        return await asyncio.gather(*tasks)

    async def _download_one_guarded(self, project: Project, *, overwrite: bool) -> DownloadResult:
        async with self._semaphore:
            try:
                return await self._download_one(project, overwrite=overwrite)
            except SessionExpiredError:
                # Bubble up — re-auth must happen at the CLI/orchestration layer.
                raise
            except Exception as exc:
                logger.exception("download failed for %s", project.id)
                return DownloadResult(
                    project_id=project.id,
                    path=self._output_dir / safe_filename(project),
                    bytes_written=0,
                    error=str(exc),
                )

    async def _download_one(self, project: Project, *, overwrite: bool) -> DownloadResult:
        destination = self._output_dir / safe_filename(project)
        if destination.exists() and not overwrite and destination.stat().st_size > 0:
            logger.info("skip %s (already exists)", destination.name)
            if self._on_progress is not None:
                self._on_progress(
                    project.id, destination.stat().st_size, destination.stat().st_size
                )
            return DownloadResult(
                project_id=project.id,
                path=destination,
                bytes_written=destination.stat().st_size,
                skipped=True,
            )

        try:
            async for attempt in AsyncRetrying(
                stop=stop_after_attempt(self._max_attempts),
                wait=wait_exponential(multiplier=1.0, max=30.0),
                retry=retry_if_exception_type((httpx.HTTPError, APIError)),
                reraise=True,
            ):
                with attempt:
                    bytes_written = await self._stream_to_disk(project, destination)
        except RetryError as exc:
            raise DownloadError(project.id, f"retries exhausted: {exc}") from exc

        return DownloadResult(
            project_id=project.id,
            path=destination,
            bytes_written=bytes_written,
        )

    async def _stream_to_disk(self, project: Project, destination: Path) -> int:
        info = await self._client.get_download_info(project.id)
        if info is not None:
            url = info.url
            request_method = "GET"
            stream_kwargs: dict[str, object] = {}
        else:
            # The /download endpoint streams the bytes directly.
            url = "/api/projects/download"
            request_method = "GET"
            stream_kwargs = {"params": {"id": project.id}}

        tmp_path = destination.with_suffix(destination.suffix + ".part")
        resume_from = tmp_path.stat().st_size if tmp_path.exists() else 0
        headers: dict[str, str] = {}
        if resume_from > 0:
            headers["Range"] = f"bytes={resume_from}-"
            logger.info("resuming %s from byte %d", destination.name, resume_from)

        mode = "ab" if resume_from > 0 else "wb"
        total_bytes = resume_from

        request_kwargs: dict[str, Any] = dict(stream_kwargs)
        if headers:
            request_kwargs["headers"] = headers

        async with self._client.http.stream(
            request_method,
            url,
            **request_kwargs,
        ) as response:
            if response.status_code == 401:
                raise SessionExpiredError(f"download for {project.id} returned 401")
            if response.status_code == 416 and resume_from > 0:
                # Server doesn't support partial — start over.
                tmp_path.unlink(missing_ok=True)
                return await self._stream_to_disk(project, destination)
            if response.status_code >= 400:
                detail = (await response.aread()).decode("utf-8", "replace")[:200]
                raise APIError(response.status_code, detail or response.reason_phrase, endpoint=url)

            content_length = response.headers.get("content-length")
            total_expected: int | None = None
            if content_length and content_length.isdigit():
                total_expected = int(content_length) + resume_from

            content_disposition = response.headers.get("content-disposition", "")
            disposition_match = _CONTENT_DISPOSITION_FILENAME.search(content_disposition)
            if disposition_match:
                hinted = disposition_match.group("value").strip()
                if hinted:
                    hinted_path = destination.with_name(
                        _FILENAME_SAFE.sub("_", hinted) or destination.name
                    )
                    if hinted_path != destination:
                        # Move tmp to follow the hinted destination too.
                        new_tmp = hinted_path.with_suffix(hinted_path.suffix + ".part")
                        if tmp_path.exists():
                            tmp_path.rename(new_tmp)
                        tmp_path = new_tmp
                        destination = hinted_path

            with tmp_path.open(mode) as fh:
                async for chunk in response.aiter_bytes(self._chunk_size):
                    if not chunk:
                        continue
                    fh.write(chunk)
                    total_bytes += len(chunk)
                    if self._on_progress is not None:
                        self._on_progress(project.id, total_bytes, total_expected)

        tmp_path.rename(destination)
        return total_bytes
