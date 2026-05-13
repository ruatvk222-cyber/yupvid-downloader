"""Tests for the cookie file parser."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from yupvid_downloader.cookies import load_cookies
from yupvid_downloader.errors import CookieFileError


def test_load_netscape_cookies(tmp_path: Path) -> None:
    path = tmp_path / "cookies.txt"
    path.write_text(
        "# Netscape HTTP Cookie File\n"
        "# This is a comment\n"
        ".yupvid.com\tTRUE\t/\tTRUE\t1999999999\tnewsvideo_session\tabc123\n"
        "#HttpOnly_.yupvid.com\tTRUE\t/\tTRUE\t1999999999\tother\txyz\n"
        ".example.com\tTRUE\t/\tFALSE\t1999999999\tunrelated\tnope\n",
        encoding="utf-8",
    )
    cookies = load_cookies(path)
    assert cookies == {"newsvideo_session": "abc123", "other": "xyz"}


def test_load_json_cookies(tmp_path: Path) -> None:
    path = tmp_path / "cookies.json"
    path.write_text(
        json.dumps(
            [
                {"name": "newsvideo_session", "value": "abc", "domain": "yupvid.com"},
                {"name": "leaked", "value": "v", "domain": "example.com"},
                {"name": "no_value", "domain": "yupvid.com"},
            ]
        ),
        encoding="utf-8",
    )
    cookies = load_cookies(path)
    assert cookies == {"newsvideo_session": "abc"}


def test_load_missing_file(tmp_path: Path) -> None:
    with pytest.raises(CookieFileError, match="not found"):
        load_cookies(tmp_path / "missing.txt")


def test_load_empty_file(tmp_path: Path) -> None:
    path = tmp_path / "empty.txt"
    path.write_text("", encoding="utf-8")
    with pytest.raises(CookieFileError, match="empty"):
        load_cookies(path)


def test_load_no_matching_cookies(tmp_path: Path) -> None:
    path = tmp_path / "cookies.txt"
    path.write_text(
        ".example.com\tTRUE\t/\tFALSE\t1999999999\tx\ty\n",
        encoding="utf-8",
    )
    with pytest.raises(CookieFileError, match="no cookies"):
        load_cookies(path)
