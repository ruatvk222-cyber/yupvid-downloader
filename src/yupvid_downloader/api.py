"""Thin client over the YupVid HTTP API.

The endpoints used here were inferred by probing ``yupvid.com`` (logged-out responses)
and by reading the public landing page. They are stable enough for the listing /
downloading flows; the higher-write endpoints (``/api/projects/create`` etc.) are
out of scope for this tool.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from yupvid_downloader.errors import APIError, SessionExpiredError
from yupvid_downloader.models import DownloadInfo, Project, parse_project_list

logger = logging.getLogger(__name__)


class YupVidClient:
    """Async wrapper around :class:`httpx.AsyncClient` for YupVid project endpoints."""

    def __init__(self, http: httpx.AsyncClient) -> None:
        self._http = http

    @property
    def http(self) -> httpx.AsyncClient:
        """Underlying HTTP client (exposed for downloader streaming)."""
        return self._http

    async def list_projects(
        self,
        *,
        page: int | None = None,
        page_size: int | None = None,
    ) -> list[Project]:
        """Return all projects belonging to the authenticated user.

        Tries the dedicated ``/api/projects/list`` first, then falls back to the
        bare ``/api/projects`` collection if the former is not exposed.
        """
        params: dict[str, Any] = {}
        if page is not None:
            params["page"] = page
        if page_size is not None:
            params["pageSize"] = page_size

        for path in ("/api/projects/list", "/api/projects"):
            response = await self._http.get(path, params=params or None)
            if response.status_code == 404:
                continue
            self._raise_for_status(response, path)
            try:
                payload = response.json()
            except ValueError as exc:
                raise APIError(
                    response.status_code,
                    f"expected JSON from {path}, got {response.text[:200]!r}",
                    endpoint=path,
                ) from exc
            return parse_project_list(payload)
        raise APIError(
            404, "no project listing endpoint available", endpoint="/api/projects[/list]"
        )

    async def get_download_info(self, project_id: str) -> DownloadInfo | None:
        """Ask the API for download metadata.

        Returns ``None`` when the endpoint streams the bytes directly (in which
        case the caller should download via :meth:`stream_download`).
        """
        response = await self._http.get(
            "/api/projects/download",
            params={"id": project_id},
        )
        self._raise_for_status(response, "/api/projects/download")
        content_type = response.headers.get("content-type", "")
        if content_type.startswith("application/json"):
            try:
                payload = response.json()
            except ValueError as exc:
                raise APIError(
                    response.status_code,
                    "download endpoint returned invalid JSON",
                    endpoint="/api/projects/download",
                ) from exc
            if isinstance(payload, dict) and "url" in payload:
                return DownloadInfo.model_validate(payload)
            if isinstance(payload, dict) and "downloadUrl" in payload:
                return DownloadInfo.model_validate({"url": payload["downloadUrl"], **payload})
            raise APIError(
                response.status_code,
                f"unexpected JSON shape from /api/projects/download: {payload!r}",
                endpoint="/api/projects/download",
            )
        # Binary stream — caller should re-issue as a streaming request.
        return None

    def _raise_for_status(self, response: httpx.Response, endpoint: str) -> None:
        if response.status_code == 401:
            raise SessionExpiredError(
                f"{endpoint} returned 401 — your session has expired. "
                "Run `yupvid-dl login` again or re-export your cookies."
            )
        if response.status_code >= 400:
            message = _safe_error_message(response)
            raise APIError(response.status_code, message, endpoint=endpoint)


def _safe_error_message(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        return response.text[:200] or response.reason_phrase
    if isinstance(payload, dict):
        for key in ("error", "message", "detail"):
            value = payload.get(key)
            if isinstance(value, str):
                return value
    return str(payload)[:200]
