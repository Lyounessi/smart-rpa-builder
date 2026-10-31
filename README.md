# Smart RPA Builder — Powered by Muse

Smart RPA Builder turns captured web elements and plain-language workflow instructions into Python automation robots using Meta Muse. Define the work, map input data, review the generated code, then run the robot and inspect its results.

The MVP supports web inspection, CSV/XLSX inputs, guided robot generation, reviewed local execution, technical logs and dated processing results. Desktop automation and scheduling are not implemented yet.

## Install locally

The current setup targets **Windows with Python 3.13**. It uses Django 5.2 LTS, SQLite, HTMX and Playwright. No Node.js build is required.

```powershell
git clone https://github.com/Lyounessi/smart-rpa-builder.git
cd smart-rpa-builder
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-inspector.lock.txt
.\.venv\Scripts\python.exe -m playwright install chromium
Copy-Item .env.example .env
```

Generate a Django secret key:

```powershell
.\.venv\Scripts\python.exe -c "import secrets; print(secrets.token_urlsafe(50))"
```

Open `.env` and replace `DJANGO_SECRET_KEY` with that value. Then initialize the database and start the app:

```powershell
.\.venv\Scripts\python.exe manage.py migrate
.\.venv\Scripts\python.exe manage.py runserver 127.0.0.1:8000 --noreload
```

Open [Smart RPA Builder](http://127.0.0.1:8000/). Keep the local server bound to `127.0.0.1`; this MVP is a single-user development workspace. `--noreload` prevents inspection browsers being interrupted by automatic restarts.

## Configure your Muse API key

Put your **Meta Muse API key** in the local `.env` file:

```dotenv
MUSE_APIKEY=your_meta_muse_api_key
META_MODEL=muse-spark-1.3
META_TIMEOUT_SECONDS=45
```

The key is read by the backend. Do not commit `.env` or put the key in workflow instructions. Existing process environment variables take precedence over `.env`. Restart Django after changing configuration.

An API key is required for Muse review and robot generation. Creating projects, capturing elements, preparing a local plan and viewing results do not require one. Paid requests are explicit; loading a page does not call Muse.

Optional connection test — **makes one small paid API request**:

```powershell
.\.venv\Scripts\python.exe manage.py check_muse_connection
```

Set `MUSE_BUDGET_USD` in `.env` to your intended local spending limit; the example defaults to `140`. **Muse usage** in the app shows estimates and reservations, not your provider account balance. See [API configuration and troubleshooting](docs/muse-integration.md) for details.

## Use the app

1. Create a project, add a target website and define input fields.
2. Add workflow steps, capture their targets, and map Fill/Select actions to input fields.
3. Upload a CSV/XLSX dataset or enter records manually, then confirm it.
4. Open **Build with Muse**: prepare the plan locally, choose what runs before/per record/after processing, and define success and failure rules. Use paid Muse help only when needed, then confirm and generate a draft.
5. Review the generated code and choose **Run robot**. Pending records are processed; confirmed treatments appear in **Results** with dates, outputs and links to logs.

Generated Python runs with local permissions. Static validation does not replace code review before execution.

## Guides

See the [documentation index](docs/README.md) for inspection, datasets, generation, execution, results and developer guides. Keep detailed feature instructions in those files rather than expanding this quick start.

## License

[MIT](LICENSE).
