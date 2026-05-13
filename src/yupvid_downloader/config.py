"""Runtime configuration for yupvid-downloader.

Reads from environment variables (and an optional ``.env`` file in the working
directory) with sensible defaults. Nothing here touches the OS keyring — see
:mod:`yupvid_downloader.auth` for credential storage.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _load_dotenv(path: Path) -> None:
    """Minimal ``.env`` loader that does not pull in python-dotenv.

    Only ``KEY=value`` lines are parsed; quotes around values are stripped.
    Existing environment variables are not overridden.
    """
    if not path.is_file():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


_load_dotenv(Path.cwd() / ".env")


DEFAULT_BASE_URL = "https://yupvid.com"
DEFAULT_OUTPUT_DIR = Path("./videos")
DEFAULT_CONCURRENCY = 3
DEFAULT_TIMEOUT_S = 60.0
DEFAULT_USER_AGENT = "yupvid-downloader/0.1 (+https://github.com/ruatvk222-cyber/yupvid-downloader)"
SESSION_COOKIE_NAME = "newsvideo_session"


@dataclass(frozen=True)
class Settings:
    """Resolved runtime settings."""

    base_url: str
    output_dir: Path
    concurrency: int
    timeout_s: float
    user_agent: str
    email: str | None
    password: str | None
    cookies_file: Path | None

    @classmethod
    def from_env(cls) -> Settings:
        cookies_file_env = os.getenv("YUPVID_COOKIES_FILE")
        return cls(
            base_url=os.getenv("YUPVID_BASE_URL", DEFAULT_BASE_URL).rstrip("/"),
            output_dir=Path(os.getenv("YUPVID_OUTPUT_DIR", str(DEFAULT_OUTPUT_DIR))),
            concurrency=int(os.getenv("YUPVID_CONCURRENCY", str(DEFAULT_CONCURRENCY))),
            timeout_s=float(os.getenv("YUPVID_TIMEOUT", str(DEFAULT_TIMEOUT_S))),
            user_agent=os.getenv("YUPVID_USER_AGENT", DEFAULT_USER_AGENT),
            email=os.getenv("YUPVID_EMAIL") or None,
            password=os.getenv("YUPVID_PASSWORD") or None,
            cookies_file=Path(cookies_file_env) if cookies_file_env else None,
        )
