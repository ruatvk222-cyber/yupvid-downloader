"""Command-line interface for yupvid-downloader.

Subcommands:

* ``login`` — store credentials and obtain a session cookie.
* ``logout`` — clear the saved session for an email.
* ``list`` — print the authenticated user's projects.
* ``download`` — bulk-download MP4s for one or more (or all) projects.
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
from getpass import getpass
from pathlib import Path
from typing import Any

import click
from rich.console import Console
from rich.logging import RichHandler
from rich.progress import (
    BarColumn,
    DownloadColumn,
    Progress,
    TaskID,
    TextColumn,
    TimeRemainingColumn,
    TransferSpeedColumn,
)
from rich.table import Table

from yupvid_downloader._version import __version__
from yupvid_downloader.api import YupVidClient
from yupvid_downloader.auth import (
    authenticated_client,
    clear_saved_session,
)
from yupvid_downloader.config import Settings
from yupvid_downloader.downloader import BulkDownloader, DownloadResult, safe_filename
from yupvid_downloader.errors import AuthError, CookieFileError, YupVidError
from yupvid_downloader.models import Project

console = Console()
err_console = Console(stderr=True, style="bold red")


def _configure_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(message)s",
        datefmt="[%X]",
        handlers=[RichHandler(console=console, show_path=False, rich_tracebacks=True)],
    )


@click.group(context_settings={"help_option_names": ["-h", "--help"]})
@click.version_option(__version__, prog_name="yupvid-dl")
@click.option("-v", "--verbose", is_flag=True, help="Enable debug logging.")
@click.pass_context
def cli(ctx: click.Context, verbose: bool) -> None:
    """Bulk-download your own rendered videos from YupVid."""
    _configure_logging(verbose)
    ctx.ensure_object(dict)
    ctx.obj["settings"] = Settings.from_env()


@cli.command()
@click.option("--email", help="YupVid account email. Prompts if omitted.")
@click.option(
    "--password",
    help="YupVid password. Prompts (hidden input) if omitted. Avoid passing on CLI.",
)
@click.pass_context
def login(ctx: click.Context, email: str | None, password: str | None) -> None:
    """Authenticate and persist the session cookie in your OS keyring."""
    settings: Settings = ctx.obj["settings"]
    email = email or settings.email or click.prompt("Email", type=str)
    password = password or settings.password or getpass("Password: ")

    async def _run() -> None:
        async with authenticated_client(
            settings,
            email=email,
            password=password,
            use_saved_session=False,
        ) as client:
            api = YupVidClient(client)
            # Validate by hitting the listing endpoint.
            projects = await api.list_projects()
            console.print(
                f"[green]Logged in as {email}.[/green] "
                f"Found {len(projects)} project(s). Session saved to keyring."
            )

    _run_or_die(_run())


@cli.command()
@click.option("--email", required=True, help="Account whose saved session to clear.")
def logout(email: str) -> None:
    """Remove the saved session cookie for ``email``."""
    clear_saved_session(email)
    console.print(f"Cleared saved session for [bold]{email}[/bold].")


@cli.command(name="list")
@click.option(
    "--json",
    "as_json",
    is_flag=True,
    help="Emit raw JSON instead of a formatted table (useful for piping).",
)
@click.option(
    "--ready-only/--all",
    "ready_only",
    default=False,
    help="Only list projects with a completed render (default: list everything).",
)
@click.pass_context
def list_projects(ctx: click.Context, as_json: bool, ready_only: bool) -> None:
    """List the authenticated user's projects."""
    settings: Settings = ctx.obj["settings"]

    async def _run() -> None:
        async with authenticated_client(settings) as client:
            api = YupVidClient(client)
            projects = await api.list_projects()
        if ready_only:
            projects = [p for p in projects if p.is_ready]
        if as_json:
            payload = [p.model_dump(mode="json", by_alias=True) for p in projects]
            click.echo(json.dumps(payload, indent=2, default=str))
            return
        _render_table(projects)

    _run_or_die(_run())


def _render_table(projects: list[Project]) -> None:
    if not projects:
        console.print("[yellow]No projects found.[/yellow]")
        return
    table = Table(title=f"YupVid projects ({len(projects)})", show_lines=False)
    table.add_column("ID", style="cyan", no_wrap=True)
    table.add_column("Title", style="bold")
    table.add_column("Status")
    table.add_column("Lang", justify="center")
    table.add_column("Duration", justify="right")
    table.add_column("Created", style="dim")
    for project in projects:
        duration = (
            f"{project.duration_seconds:.0f}s" if project.duration_seconds is not None else "—"
        )
        created = project.created_at.isoformat(timespec="seconds") if project.created_at else "—"
        status = project.status or ("ready" if project.is_ready else "—")
        table.add_row(
            project.id,
            project.display_title,
            status,
            project.language or "—",
            duration,
            created,
        )
    console.print(table)


@cli.command()
@click.option(
    "--all",
    "download_all",
    is_flag=True,
    help="Download every ready project for the authenticated user.",
)
@click.option(
    "--ids",
    "ids_csv",
    help="Comma-separated project ids to download (overrides --all).",
)
@click.option(
    "--ids-file",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="File with one project id per line (combined with --ids).",
)
@click.option(
    "--output",
    "-o",
    type=click.Path(file_okay=False, path_type=Path),
    default=None,
    help="Output directory (default: $YUPVID_OUTPUT_DIR or ./videos).",
)
@click.option(
    "--concurrency",
    "-c",
    type=click.IntRange(min=1, max=16),
    default=None,
    help="Number of parallel downloads (default: 3).",
)
@click.option(
    "--overwrite",
    is_flag=True,
    help="Re-download even if the destination file already exists.",
)
@click.option(
    "--dry-run",
    is_flag=True,
    help="Print what would be downloaded without making download requests.",
)
@click.pass_context
def download(
    ctx: click.Context,
    download_all: bool,
    ids_csv: str | None,
    ids_file: Path | None,
    output: Path | None,
    concurrency: int | None,
    overwrite: bool,
    dry_run: bool,
) -> None:
    """Download one, several, or all of your rendered videos as MP4."""
    settings: Settings = ctx.obj["settings"]
    output_dir = output or settings.output_dir
    conc = concurrency or settings.concurrency

    wanted_ids = _collect_ids(ids_csv, ids_file)
    if not wanted_ids and not download_all:
        raise click.UsageError("Pass --all, --ids, or --ids-file.")

    async def _run() -> None:
        async with authenticated_client(settings) as client:
            api = YupVidClient(client)
            all_projects = await api.list_projects()
            target = _select_targets(all_projects, wanted_ids, download_all=download_all)
            if not target:
                console.print("[yellow]Nothing to download.[/yellow]")
                return

            console.print(
                f"Selected [bold]{len(target)}[/bold] project(s); writing to "
                f"[cyan]{output_dir}[/cyan] with concurrency [bold]{conc}[/bold]."
            )
            if dry_run:
                for project in target:
                    console.print(
                        f"  • {project.id}  {project.display_title}  → "
                        f"{output_dir / safe_filename(project)}"
                    )
                return

            results = await _run_downloads(api, target, output_dir, conc, overwrite)
        _summarize(results)

    _run_or_die(_run())


def _collect_ids(ids_csv: str | None, ids_file: Path | None) -> set[str]:
    ids: set[str] = set()
    if ids_csv:
        ids.update(part.strip() for part in ids_csv.split(",") if part.strip())
    if ids_file:
        for line in ids_file.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped and not stripped.startswith("#"):
                ids.add(stripped)
    return ids


def _select_targets(
    projects: list[Project],
    wanted_ids: set[str],
    *,
    download_all: bool,
) -> list[Project]:
    by_id = {p.id: p for p in projects}
    if wanted_ids:
        missing = wanted_ids - by_id.keys()
        if missing:
            err_console.print(
                f"warning: {len(missing)} id(s) not found in your account: {sorted(missing)!r}"
            )
        return [by_id[i] for i in wanted_ids if i in by_id]
    if download_all:
        return [p for p in projects if p.is_ready]
    return []


async def _run_downloads(
    api: YupVidClient,
    projects: list[Project],
    output_dir: Path,
    concurrency: int,
    overwrite: bool,
) -> list[DownloadResult]:
    progress = Progress(
        TextColumn("[bold]{task.fields[title]}", justify="left"),
        BarColumn(),
        DownloadColumn(),
        TransferSpeedColumn(),
        TimeRemainingColumn(),
        console=console,
        transient=False,
    )
    task_ids: dict[str, TaskID] = {}

    def on_progress(project_id: str, written: int, total: int | None) -> None:
        task_id = task_ids.get(project_id)
        if task_id is None:
            return
        if total is not None:
            progress.update(task_id, total=total)
        progress.update(task_id, completed=written)

    downloader = BulkDownloader(
        api,
        output_dir,
        concurrency=concurrency,
        on_progress=on_progress,
    )

    with progress:
        for project in projects:
            task_ids[project.id] = progress.add_task(
                "download",
                title=project.display_title[:48],
                total=None,
                start=True,
            )
        return await downloader.download_many(projects, overwrite=overwrite)


def _summarize(results: list[DownloadResult]) -> None:
    ok = [r for r in results if r.ok and not r.skipped]
    skipped = [r for r in results if r.skipped]
    failed = [r for r in results if not r.ok]

    console.rule("Summary")
    console.print(f"  Downloaded: [green]{len(ok)}[/green]")
    console.print(f"  Skipped:    [yellow]{len(skipped)}[/yellow] (already on disk)")
    console.print(f"  Failed:     [red]{len(failed)}[/red]")
    if failed:
        for result in failed:
            err_console.print(f"  ✗ {result.project_id}: {result.error}")
        sys.exit(2)


def _run_or_die(coro: Any) -> None:
    try:
        asyncio.run(coro)
    except (AuthError, CookieFileError) as exc:
        err_console.print(f"auth error: {exc}")
        sys.exit(1)
    except YupVidError as exc:
        err_console.print(f"error: {exc}")
        sys.exit(1)


def main() -> None:
    cli(obj={})


if __name__ == "__main__":
    main()
