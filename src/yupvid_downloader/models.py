"""Pydantic models for YupVid API responses.

Keeps the schema permissive (``extra="ignore"``) because we are reverse-engineering
the API surface and the server may add fields without notice. The fields we depend
on are explicit and validated.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Project(BaseModel):
    """A single rendered project as returned by ``/api/projects/list``."""

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    id: str
    title: str | None = Field(default=None)
    status: str | None = Field(default=None)
    language: str | None = Field(default=None)
    duration_seconds: float | None = Field(default=None, alias="durationSeconds")
    created_at: datetime | None = Field(default=None, alias="createdAt")
    updated_at: datetime | None = Field(default=None, alias="updatedAt")
    rendered_at: datetime | None = Field(default=None, alias="renderedAt")
    video_url: str | None = Field(default=None, alias="videoUrl")
    download_url: str | None = Field(default=None, alias="downloadUrl")
    thumbnail_url: str | None = Field(default=None, alias="thumbnailUrl")

    @field_validator("id", mode="before")
    @classmethod
    def _coerce_id(cls, value: Any) -> str:
        # Some endpoints return numeric ids; normalize to str so filenames are stable.
        return str(value)

    @property
    def display_title(self) -> str:
        return self.title or f"project-{self.id}"

    @property
    def is_ready(self) -> bool:
        """True when the project has a downloadable artifact."""
        if self.status and self.status.lower() in {"ready", "done", "completed", "rendered"}:
            return True
        return bool(self.video_url or self.download_url)


class ProjectListResponse(BaseModel):
    """Envelope returned by ``/api/projects/list``.

    The real API may use one of several shapes (``{"items": [...]}``,
    ``{"projects": [...]}``, or a bare list). :func:`parse_project_list` handles
    all three by delegating to this model after normalization.
    """

    model_config = ConfigDict(extra="ignore")

    items: list[Project] = Field(default_factory=list)
    total: int | None = None
    page: int | None = None
    page_size: int | None = Field(default=None, alias="pageSize")


def parse_project_list(payload: Any) -> list[Project]:
    """Normalize the various known list shapes into ``list[Project]``."""
    if isinstance(payload, list):
        return [Project.model_validate(item) for item in payload]
    if isinstance(payload, dict):
        for key in ("items", "projects", "data", "results"):
            value = payload.get(key)
            if isinstance(value, list):
                return [Project.model_validate(item) for item in value]
        if "id" in payload:  # single project returned bare
            return [Project.model_validate(payload)]
    return []


class DownloadInfo(BaseModel):
    """Response from ``/api/projects/download`` when it returns JSON metadata.

    Some routes stream the file directly (Content-Type: video/mp4). Others return
    a presigned CDN URL that the client must follow. The downloader handles both.
    """

    model_config = ConfigDict(extra="ignore")

    url: str
    filename: str | None = None
    content_type: str | None = Field(default=None, alias="contentType")
    size_bytes: int | None = Field(default=None, alias="sizeBytes")
