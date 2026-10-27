# Smart RPA Builder — Powered by Muse

Smart RPA Builder is a web platform designed to help businesses and individuals create robots that automate repetitive work without writing code.

Users will define workflows through screenshots, captured interface elements, and short step-by-step instructions. Meta Muse will use this context to generate robots that run through a Python automation framework.

The planned platform will support inspecting web and Windows desktop applications, running robots, reviewing execution logs, and refining workflows.

> **Status:** Django foundation implemented. Workflow editing, browser inspection, Muse integration, and robot execution are still planned.

## Local setup (Windows PowerShell)

Use Python 3.13. The backend uses Django 5.2 LTS and SQLite. Templates use locally bundled HTMX 2.0.11; Node.js and a frontend build are not required.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
.\.venv\Scripts\python.exe -c "import secrets; print(secrets.token_urlsafe(50))"
```

Replace `DJANGO_SECRET_KEY` in `.env` with the generated value, then run:

```powershell
.\.venv\Scripts\python.exe manage.py migrate
.\.venv\Scripts\python.exe manage.py runserver 127.0.0.1:8000
```

Open http://127.0.0.1:8000 and use **Check platform status** to exercise the HTMX HTML fragment endpoint. This is a foundation page, not yet the workflow editor.

Optional Django admin account:

```powershell
.\.venv\Scripts\python.exe manage.py createsuperuser
```

`accounts.User` extends `AbstractUser` and is configured before the initial migration. Registration and role screens are deferred.

## Environment and dependencies

- `.env.example` documents local settings; `.env` is ignored by Git. Existing environment variables take precedence over the file.
- A secret key is required. Debug defaults to false; the example enables it for local development. Keep this single-user development server bound to loopback.
- SQLite is stored in `db.sqlite3`; future captures go into `media/`. Both are ignored by Git. Back up both together once capture is implemented.
- `requirements.txt` allows patch updates within Django 5.2 LTS. `requirements.lock.txt` records the exact verified runtime dependencies; install it instead for a reproducible environment.
- `requirements-inspector.txt` adds Playwright for the upcoming inspector milestone. Browser installation will also be needed: `python -m playwright install chromium` using the virtual environment's Python. Browser capture is not implemented yet.
- HTMX is vendored in `static/vendor/` with its license. Django retains CSRF protection; future mutation forms must include `{% csrf_token %}`. `static/app.js` forwards that token for same-origin HTMX requests.
- No Muse API key is needed at this stage. Never commit actual credentials or include them in model context.

## Checks

```powershell
.\.venv\Scripts\python.exe manage.py check
.\.venv\Scripts\python.exe manage.py makemigrations --check --dry-run
.\.venv\Scripts\python.exe manage.py test
```

## First Component: Inspector Tool

The inspector will help users capture the interface elements required for an automation, such as fields, buttons, and menus.

Each captured element will be saved with its locator, screenshot, and metadata, and linked to a project in the database. Users will reference these elements when describing workflow steps.

Muse will use the captured elements, workflow instructions, and framework documentation to build the robot.

## Hackathon Contributions

This project is being built during the hackathon, from October 26 to November 4, 2026. Implemented features and setup instructions will be added as development progresses.

## License

This project is licensed under the [MIT License](LICENSE).
