# AIResume · 叙职

[简体中文](README.md) | **English**

> Describe what you've done, more clearly.

AIResume (叙职) is an online resume editing tool for students and recent graduates. Upload an existing resume and provide a target job description, then review suggestions alongside your original text and the job requirements. Add details from your actual experience and export an editable Word resume.

The workflow focuses on a specific job application. It reviews your resume from three perspectives: structure and readability, how you describe your experience, and relevance to the role. Each suggestion includes references you can check. Accept, skip, or edit individual suggestions; when details are missing, confirm the facts before generating a rewrite. You decide which changes to keep.

[Try it online](https://key123456.online/app/) · [Explore the fictional demo](https://key123456.online/app/?demo=1) · [Data handling](https://key123456.online/privacy/)

The interface and analysis prompts are currently primarily in Chinese.

## Features

- **Word and PDF import**: Read DOC, DOCX (including text boxes), and PDFs with selectable text. Review the extracted resume before starting analysis.
- **Suggestions based on the target role**: See the reason for each change, the original resume text, the relevant job requirement, and its priority.
- **Review changes individually**: Accept, skip, undo, or edit suggestions. Supply factual details when more information is needed for a rewrite.
- **Preview and Word export**: Apply accepted changes to a consistent, simple layout, preview the result, and download an editable DOCX.
- **Choose your model service**: See the site-provided model ID, use a built-in provider or custom API, fetch available models, save multiple model IDs, and switch the model used for an analysis.
- **No account required**: Start without registering, or explore a fictional demo that makes no model calls.
- **Text scaling and small screens**: Interface text follows user font-size settings, headings and controls can reflow, and model input handles Chinese IME confirmation safely.

## How to use

1. **Prepare your materials**: Upload a Word document or a PDF with selectable text, then paste the target role's responsibilities and requirements.
2. **Check the extracted content**: Verify your name, education, projects, and work experience before starting analysis.
3. **Review each suggestion**: Compare the proposed change with its references. Accept, skip, or edit it, and add factual details when needed.
4. **Preview and export**: Check the result, download the Word document, and end the session.

## Model services

Open **模型设置** (Model settings) in the upper-right corner of the workspace. You can use the site-provided model, enter your own DeepSeek API key, or connect another service through a custom API. A custom configuration includes a Provider ID, display name, API base URL, protocol, API key, and model list. Supported protocols are OpenAI Chat Completions, OpenAI Responses, and Anthropic Messages.

Each browser can persistently save up to **3 custom API configurations**, with editing, deletion, and switching supported. A configuration can contain multiple models. Click a model in the list to make it the default; when using the configuration, you can select another model or enter an ID outside the saved list. API URLs must use public HTTPS endpoints. If model discovery is unavailable, add model IDs manually. Configurations and keys stay in the current browser and do not sync across browsers or devices. During a request, the key is temporarily passed to the backend; it is not written to server-side sessions, files, or logs.

The workspace and model settings show the model ID and protocol configured by the site operator. Operators can select a protocol with `RESUME_LLM_PROTOCOL`; the frontend does not receive the site's API key or base URL. A model ID may be a provider-defined alias, so consult the provider for the underlying model.

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

Requires Node.js 24, Python 3.12, and uv. Starting from the repository root, install dependencies:

```powershell
cd web
npm ci
cd ../api
uv sync --group dev
```

Open two terminals at the repository root and run one command in each:

```powershell
./scripts/dev.ps1 api
./scripts/dev.ps1 web
```

Open the [local workspace](http://127.0.0.1:4321/app/). See [api/.env.example](api/.env.example) to configure the site-provided model, or add your own model service in the interface. To explore without model calls, open the [local fictional demo](http://127.0.0.1:4321/app/?demo=1).

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
uv run ruff check app tests
uv run pytest -q
cd ../web
npm run check
npm run build
```

The browser workflow script, [scripts/browser_qa.py](scripts/browser_qa.py), uses a simulated model and page-count service. Ubuntu integration tests verify the actual isolated document service. Model availability and generation quality need to be verified separately with the selected provider.

The frontend follows [Modern Web Guidance](https://github.com/GoogleChrome/modern-web-guidance), progressively enhancing typography, forms, and accessibility according to browser support.
