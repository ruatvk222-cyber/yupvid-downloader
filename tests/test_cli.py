"""Smoke tests for the Click CLI."""

from __future__ import annotations

from click.testing import CliRunner

from yupvid_downloader._version import __version__
from yupvid_downloader.cli import cli


def test_cli_help() -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["--help"])
    assert result.exit_code == 0
    assert "Bulk-download" in result.output
    for command in ("login", "logout", "list", "download"):
        assert command in result.output


def test_cli_version() -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["--version"])
    assert result.exit_code == 0
    assert __version__ in result.output


def test_download_requires_target() -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["download"])
    assert result.exit_code != 0
    assert "--all" in result.output or "Pass --all" in result.output
