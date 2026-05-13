"""Parse cookie files exported from browsers.

Supports two formats:

* **Netscape ``cookies.txt``** — exported by extensions like *Get cookies.txt*
  (Chrome) or by ``curl --cookie-jar``. Each line is tab-separated:
  ``domain\\tflag\\tpath\\tsecure\\texpiration\\tname\\tvalue``.
* **JSON array** — exported by *EditThisCookie* and similar extensions:
  ``[{"name": "...", "value": "...", "domain": "...", ...}, ...]``.

We only extract cookies whose host matches a ``yupvid.com`` suffix.
"""

from __future__ import annotations

import json
from pathlib import Path

from yupvid_downloader.errors import CookieFileError


def _host_matches(host: str, domain: str) -> bool:
    host = host.lower().lstrip(".")
    domain = domain.lower().lstrip(".")
    return host == domain or host.endswith("." + domain)


def load_cookies(path: Path, target_domain: str = "yupvid.com") -> dict[str, str]:
    """Return a ``{name: value}`` dict of cookies for ``target_domain``.

    Raises:
        CookieFileError: file missing, malformed, or contains no usable cookies.
    """
    if not path.is_file():
        raise CookieFileError(f"cookie file not found: {path}")

    raw = path.read_text(encoding="utf-8").strip()
    if not raw:
        raise CookieFileError(f"cookie file is empty: {path}")

    if raw[0] in "[{":
        cookies = _parse_json(raw, target_domain)
    else:
        cookies = _parse_netscape(raw, target_domain)

    if not cookies:
        raise CookieFileError(
            f"no cookies for {target_domain} found in {path}. "
            "Make sure you exported cookies while logged in to yupvid.com."
        )
    return cookies


def _parse_json(raw: str, target_domain: str) -> dict[str, str]:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise CookieFileError(f"invalid JSON cookie file: {exc}") from exc

    if isinstance(data, dict):
        data = [data]
    if not isinstance(data, list):
        raise CookieFileError("JSON cookie file must be a list of cookie objects")

    out: dict[str, str] = {}
    for item in data:
        if not isinstance(item, dict):
            continue
        name = item.get("name")
        value = item.get("value")
        domain = item.get("domain") or item.get("host") or ""
        if not name or value is None:
            continue
        if domain and not _host_matches(domain, target_domain):
            continue
        out[str(name)] = str(value)
    return out


def _parse_netscape(raw: str, target_domain: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for raw_line in raw.splitlines():
        line = raw_line.rstrip("\n")
        if not line or line.startswith("#"):
            # ``#HttpOnly_`` prefix is sometimes used; strip it.
            if line.startswith("#HttpOnly_"):
                line = line[len("#HttpOnly_") :]
            else:
                continue
        parts = line.split("\t")
        if len(parts) < 7:
            continue
        domain, _flag, _path, _secure, _expiry, name, value = parts[:7]
        if not _host_matches(domain, target_domain):
            continue
        out[name] = value
    return out
