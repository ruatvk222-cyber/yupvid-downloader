"""Tests for response models."""

from __future__ import annotations

from yupvid_downloader.models import Project, parse_project_list


def test_parse_project_list_bare_list() -> None:
    payload = [{"id": "1", "title": "First"}, {"id": 2, "title": "Second"}]
    projects = parse_project_list(payload)
    assert [p.id for p in projects] == ["1", "2"]
    assert projects[0].display_title == "First"


def test_parse_project_list_items_envelope() -> None:
    payload = {"items": [{"id": "abc", "status": "ready"}], "total": 1}
    [project] = parse_project_list(payload)
    assert project.id == "abc"
    assert project.is_ready is True


def test_parse_project_list_projects_envelope() -> None:
    payload = {"projects": [{"id": "9", "status": "queued"}]}
    [project] = parse_project_list(payload)
    assert project.status == "queued"
    assert project.is_ready is False


def test_parse_project_list_handles_unknown_shapes() -> None:
    assert parse_project_list(None) == []
    assert parse_project_list({"unrelated": True}) == []


def test_project_is_ready_falls_back_to_video_url() -> None:
    p = Project.model_validate({"id": "x", "videoUrl": "https://cdn.yupvid.com/v.mp4"})
    assert p.is_ready is True


def test_project_display_title_default() -> None:
    p = Project.model_validate({"id": "42"})
    assert p.display_title == "project-42"
