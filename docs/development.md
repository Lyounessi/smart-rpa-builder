# Local development

Use the [quick start](../README.md) to install the full pinned environment and Chromium first.

## Environment and storage

- `.env.example` lists configuration options. `.env` is ignored by Git, and process environment variables override it.
- Set a unique `DJANGO_SECRET_KEY`. The example enables debug for local development; keep the server on loopback.
- SQLite data lives in `db.sqlite3`; captures and recordings live under `media/`. Both are ignored. Back up both together to preserve projects and referenced artifacts.
- The local editor has no sign-in requirement. Django admin uses normal authentication. Desktop/headless hosting and production deployment are outside the MVP setup.

## Dependency files

- `requirements.txt`: backend dependency ranges, including Django 5.2 LTS.
- `requirements.lock.txt`: pinned backend dependencies.
- `requirements-inspector.txt`: backend plus browser inspection dependencies.
- `requirements-inspector.lock.txt`: the complete pinned environment used by the quick start.

Chromium is installed separately with `python -m playwright install chromium` through the virtual environment. HTMX is bundled under `static/vendor/`; no frontend build is required. Mutation forms retain Django CSRF protection, including HTMX requests.

## Django admin

From the repository root in PowerShell:

```powershell
.\.venv\Scripts\python.exe manage.py createsuperuser
```

Open [Django admin](http://127.0.0.1:8000/admin/). `accounts.User` extends `AbstractUser`; public registration and role-management screens are not implemented.

## Local checks

```powershell
.\.venv\Scripts\python.exe manage.py check
.\.venv\Scripts\python.exe manage.py makemigrations --check --dry-run
.\.venv\Scripts\python.exe manage.py test
```

The normal suite does not call the real Muse API. Optional browser tests are enabled separately:

```powershell
$env:RUN_BROWSER_TESTS = '1'
.\.venv\Scripts\python.exe manage.py test
Remove-Item Env:RUN_BROWSER_TESTS
```

Use `--noreload` on the development server while inspecting: worker health checks intentionally close inspection browsers when their server restarts. Restart Django explicitly after configuration or code changes.
