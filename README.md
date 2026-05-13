# yupvid-downloader

A small Python CLI to **bulk-download your own rendered videos** from
[YupVid](https://yupvid.com) (an AI short-video studio).

> **Owner-only tool.** This client only talks to YupVid's own authenticated
> project APIs (`/api/projects/list`, `/api/projects/download`). It does **not**
> scrape, bypass paywalls, or fetch content belonging to other users. Use it on
> your own account, with your own credentials.

## Features

- Two authentication flows
  - **Email + password** — calls `POST /api/auth/login` and stores the
    `newsvideo_session` cookie in your **OS keyring** for reuse.
  - **Cookie import** — point at a `cookies.txt` (Netscape) or `cookies.json`
    file exported from your browser; no password handling.
- **List** all your projects (table or `--json`).
- **Bulk download** with:
  - configurable concurrency (`-c/--concurrency`, default 3),
  - exponential-backoff retries (HTTP errors, network blips),
  - **resume support** via HTTP `Range` for interrupted downloads,
  - safe filenames (`<sanitised-title>__<project-id>.mp4`),
  - skip-if-exists by default, `--overwrite` to force.
- Rich progress bars and clear per-project error reporting.
- Strict typing (`mypy --strict`) and lint-clean (`ruff`).

## Install

Requires **Python 3.10+**.

```bash
# From source (recommended while in development)
git clone https://github.com/ruatvk222-cyber/yupvid-downloader.git
cd yupvid-downloader

# With uv (fast, reproducible)
uv sync --extra dev
uv run yupvid-dl --help

# Or with pip
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
yupvid-dl --help
```

## Configure

Create `.env` from the template:

```bash
cp .env.example .env
$EDITOR .env
```

Available variables:

| Variable               | Default          | Purpose                                          |
|------------------------|------------------|--------------------------------------------------|
| `YUPVID_EMAIL`         | —                | Account email for password login                 |
| `YUPVID_PASSWORD`      | —                | Account password (≥ 8 chars)                     |
| `YUPVID_COOKIES_FILE`  | —                | Path to `cookies.txt` / `cookies.json` to import |
| `YUPVID_OUTPUT_DIR`    | `./videos`       | Where MP4s land                                  |
| `YUPVID_CONCURRENCY`   | `3`              | Parallel downloads                               |
| `YUPVID_TIMEOUT`       | `60`             | HTTP timeout (seconds)                           |
| `YUPVID_BASE_URL`      | `https://yupvid.com` | Override base URL (rarely useful)            |

You can skip `.env` entirely and use the keyring instead — run `yupvid-dl login`
once and your session is reused on subsequent calls.

## Usage

### Log in (one-time)

```bash
yupvid-dl login                    # prompts for email + password
yupvid-dl login --email you@x.com  # password prompt only
```

The session cookie is stored in your OS keyring under service
`yupvid-downloader` and reused automatically.

### List projects

```bash
yupvid-dl list                # pretty table
yupvid-dl list --json         # machine-readable JSON
yupvid-dl list --ready-only   # only projects with a finished render
```

### Bulk download

```bash
# All ready projects, 4 parallel, into ./videos
yupvid-dl download --all -c 4

# A specific set of ids
yupvid-dl download --ids abc123,def456 -o ./downloads

# From a file with one id per line
yupvid-dl download --ids-file ids.txt --overwrite

# Preview without downloading
yupvid-dl download --all --dry-run
```

### Cookie-file auth (no password)

Export cookies from your browser (e.g. with the *Get cookies.txt* Chrome
extension) **while you are logged in to yupvid.com**, then:

```bash
YUPVID_COOKIES_FILE=./cookies.txt yupvid-dl list
YUPVID_COOKIES_FILE=./cookies.txt yupvid-dl download --all
```

The file must contain the `newsvideo_session` cookie for `yupvid.com`.

### Log out / clear saved session

```bash
yupvid-dl logout --email you@example.com
```

## Error handling

- **401 Authentication required** → `SessionExpiredError`: rerun `yupvid-dl
  login` or re-export your cookies.
- **Network blips / 5xx** → up to 4 attempts with exponential backoff.
- **Partial files** are saved as `<filename>.part` next to the destination and
  resumed via HTTP `Range` on the next run.
- The CLI prints a per-project failure summary and exits with code `2` if any
  download failed.

## Development

```bash
uv sync --extra dev
uv run pytest        # unit tests (httpx mocked, no network)
uv run ruff check .
uv run ruff format --check .
uv run mypy
```

CI runs all of these on every push (see `.github/workflows/ci.yml`).

## Project layout

```
src/yupvid_downloader/
  __init__.py
  _version.py
  api.py          # /api/projects/* wrapper
  auth.py         # login + keyring + cookie-file auth
  cli.py          # click commands
  config.py       # Settings.from_env()
  cookies.py      # cookies.txt / cookies.json parser
  downloader.py   # async bulk downloader (retry + resume)
  errors.py
  models.py       # pydantic models
tests/
  ...
```

## License

MIT — see [LICENSE](LICENSE).
