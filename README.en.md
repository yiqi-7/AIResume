# AIResume · 叙职

[简体中文](README.md) | **English**

AIResume (叙职) is an online resume editor for students and recent graduates. Upload a resume and enter a target job description, compare suggested edits with the original text and role requirements, and export an editable Word document.

[Try it online](https://key123456.online/app/) · [Explore the fictional demo](https://key123456.online/app/?demo=1) · [Data handling](https://key123456.online/privacy/)

## Quick start

Open the [fictional demo](https://key123456.online/app/?demo=1). It needs no account, personal documents, or API key. You should see a sample resume and its suggestions under **逐条修改** (Review suggestions). Accept one suggestion, then switch to **简历预览** (Resume preview) to see the change. The demo makes no model calls and does not export Word files.

To work on your own resume, open the [online workspace](https://key123456.online/app/), upload a Word file or PDF with selectable text, and enter the target role. Check the extracted text, then analyze, edit, preview, and export to DOCX. The interface and analysis prompts are primarily in Chinese.

## Features

- **Word and PDF import**: Read DOC, DOCX (including text boxes), and PDFs with selectable text. Review the extracted resume before starting analysis.
- **Suggestions based on the target role**: See the reason for each change, the original resume text, and the relevant job requirement.
- **Review changes individually**: Accept, skip, undo, or edit suggestions. Supply factual details when more information is needed for a rewrite.
- **Preview and Word export**: Apply accepted changes to a consistent, simple layout, preview the result, and download an editable DOCX.
- **Choose your model service**: See the site-provided model ID, use a built-in provider or custom API, fetch available models, save multiple model IDs, and switch the model used for an analysis.
- **No account required**: Start without registering, or explore a fictional demo that makes no model calls.

## Model services

Click the model name in the upper-right corner of the workspace to open model settings. You can use the site-provided model, enter your own DeepSeek API key, or connect another service through a custom API. Enter a name, API base URL, and API key, then fetch or enter the model to use. Internal identifiers are generated automatically. Protocol selection is under Advanced settings. Supported protocols are OpenAI Chat Completions, OpenAI Responses, and Anthropic Messages.

Each browser can persistently save up to **3 custom API configurations**, with editing, deletion, and switching supported. A configuration can contain multiple models. Click a model in the list to make it the default; when using the configuration, you can select another model or enter an ID outside the saved list. API URLs must use public HTTPS endpoints. If model discovery is unavailable, enter a model name directly or expand the manual model section to maintain a list. Configurations and keys stay in the current browser and do not sync across browsers or devices. During a request, the key is temporarily passed to the backend; it is not written to server-side sessions, files, or logs.

The workspace and model settings show the name of the site-provided model. Its communication protocol is not shown in the regular interface. Operators can select a protocol with `RESUME_LLM_PROTOCOL`; the frontend does not receive the site's API key or base URL. A model ID may be a provider-defined alias, so consult the provider for the underlying model.

The default output budget is 8192 tokens per call, configurable through `RESUME_LLM_OUTPUT_TOKENS`. Reasoning tokens may also count toward this budget. If output is truncated, the app shows an error and preserves the original resume so you can switch models and retry.

For site-provided OpenAI-compatible services that explicitly support reasoning effort, operators can optionally set `RESUME_LLM_REASONING_EFFORT=low` (or `medium` / `high`). This parameter is omitted by default and is not applied to users' own APIs. Adjust `RESUME_LLM_TIMEOUT` and `RESUME_TASK_TIMEOUT` to suit the service's response time.

Analysis requires a working endpoint, model, and access permissions from the selected service. Fetching a model list does not guarantee access to generation. Client restrictions, permission issues, quota limits, and protocol errors are shown explicitly. The fictional demo requires no API key and makes no model calls.

## Files and data handling

- Uploads are limited to **5 MB and 8 pages**. Files exceeding the page limit are rejected with a request to shorten them. PDF import reads the text layer only; scanned and image-only PDFs are not supported. Check the extraction order for complex columns, tables, and floating text boxes.
- Exports use a shared template. The original file's fonts, images, and complex layout are not preserved. Word page counts are determined by LibreOffice on the server and may differ from those shown by Word on your computer.
- Resumes, job descriptions, and editing state are stored temporarily on the server during a session and encrypted with a server-side key. By default, a session expires after 2 hours of inactivity or 6 hours from creation, whichever comes first.
- You can end a session manually. Server-side cleanup is triggered after the export response finishes. Analysis sends resume text and structure, the job description, and any required additional facts to the selected model service. See [Data handling](https://key123456.online/privacy/) for details.

## Tech stack

| Area | Technologies |
| --- | --- |
| Frontend | Astro, React, TypeScript, Tailwind CSS, Radix UI |
| Backend | Python 3.12, FastAPI, Pydantic, HTTPX |
| Document processing | python-docx, pypdf, LibreOffice Writer |
| Sessions and deployment | Redis, encrypted file storage, nginx, systemd |

```text
web/       Pages, resume workspace, and model settings
api/       API, model calls, document processing, and tests
shared/    Resume template configuration
deploy/    nginx, isolated document service, and cleanup configuration
scripts/   Local development and browser verification scripts
```

## Run locally

The following commands use PowerShell and require Node.js 24 (with npm), Python 3.12, and uv. Clone the repository and install its dependencies:

```powershell
git clone https://github.com/yiqi-7/AIResume.git
cd AIResume
Push-Location web
npm ci
Pop-Location
Push-Location api
uv sync --locked --group dev
Pop-Location
```

To explore the fictional demo, start the frontend from the repository root:

```powershell
.\scripts\dev.ps1 web
```

Open the [local fictional demo](http://127.0.0.1:4321/app/?demo=1). You should see the suggestion list and resume preview tabs. You can skip installing the API dependencies if you only want the demo.

To start the API, run `.\scripts\dev.ps1 api` in another terminal at the repository root. The [API health check](http://127.0.0.1:8010/healthz) should return `{"status":"ok"}`; then open the [local workspace](http://127.0.0.1:4321/app/). See [api/.env.example](api/.env.example) to configure the site-provided model, or add your own model service in the interface.

### File uploads

Actual file uploads require the isolated document reading and pagination service on Linux. On Windows, you can start by exploring the fictional demo. To deploy the service:

1. Install LibreOffice Writer and Noto CJK fonts, then create a dedicated `airesume-render` user and group.
2. Install the [socket](deploy/airesume-pagecheck.socket) and [service](deploy/airesume-pagecheck.service) units. The default code path is `/opt/airesume`; the socket's `SocketGroup` is `airesume`, the API's group.
3. Keep the rendering user separate from the API user. Do not add the rendering user to the API group, and prevent other users from reading API configuration or session directories.
4. Enable the socket and verify actual uploads and available resources on the target machine.

DOC conversion, Word pagination, and PDF extraction run in a restricted, isolated process with one concurrent job, 384 MB of memory, no swap, a 96 MB temporary memory filesystem, and a 30-second job timeout. Upload materials are not saved if the isolated service is unavailable or validation fails.

## Development checks

Starting from the repository root, run:

```powershell
cd api
uv run ruff check app tests ../scripts/browser_qa.py ../deploy/generate_cloudflare_nginx.py
uv run pytest -q
cd ../web
npm run check
npm run build
```

The full [acceptance workflow](.github/workflows/checks.yml) runs Redis, nginx, and isolated document service integration checks on Ubuntu. The [browser workflow script](scripts/browser_qa.py) uses a simulated model and page-count service. Verify model availability and generation quality separately with the provider you select.

The frontend follows [Modern Web Guidance](https://github.com/GoogleChrome/modern-web-guidance), progressively enhancing typography, forms, and accessibility according to browser support.

## Feedback and license

Report problems in [GitHub Issues](https://github.com/yiqi-7/AIResume/issues) with reproduction steps and your operating system and browser versions. Use fictional resume data to reproduce the problem and keep API keys out of reports.

The repository does not currently include a project-wide license. See [OFL.txt](web/public/OFL.txt) for the font license.
