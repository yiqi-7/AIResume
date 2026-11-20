# AIResume · 叙职

AIResume is an online resume editor for students and recent graduates. Upload a resume and target job description, compare suggestions with the original text, accept or adjust individual edits, and export an editable Word document. The interface and analysis prompts are primarily in Chinese.

[Try the sample first](https://key123456.online/app/?demo=1) · [简体中文](README.md)

## Quick start: complete one edit

The sample uses a fictional resume and needs no account, upload, or model configuration. It lets you verify the editing and preview flow; it makes no model calls and cannot export files.

1. Open the [sample workspace](https://key123456.online/app/?demo=1) and select **让个人行动更容易被看见** (make your contribution easier to see).
2. Compare the original text with the job requirements. Tick **确认改写符合我的经历** (confirm the rewrite matches my experience), then click **采纳这条修改** (accept this edit).
3. Switch to **简历预览** (resume preview) and find the campus resale project, **校园二手交易平台**.

**Success looks like this:** the project description changes from “访谈同学并整理需求…” to “围绕校园二手交易场景，访谈同学并整理需求…”.

## Continue with your own resume

Prepare a DOC, DOCX, or PDF with selectable text, up to **5 MB and 8 pages**. Scans need a text layer first. Analysis requires an available model service. Use the site model, or open model settings in the upper-right corner to add your DeepSeek key or a custom API.

Open the [online workspace](https://key123456.online/app/), upload the resume, and paste the job description. Check the extracted text before starting analysis. Confirm that the suggestions match your experience, then preview and export a DOCX.

- **Exports use a standard layout** and do not preserve images or complex formatting. The server clears the session after sending the Word file, so finish editing first. You can also clear your materials manually.
- **Analysis sends resume content and the job description to the selected model.** Custom API settings and keys stay in the current browser and are forwarded through the site when used. Read the [data handling information](https://key123456.online/privacy/) before using personal materials.

## Develop and deploy (optional)

<details>
<summary>Local setup, checks, and production configuration</summary>

### Run the sample only

Requires Node.js 24 (with npm), Git, and PowerShell. Run in a new terminal:

```powershell
git clone https://github.com/yiqi-7/AIResume.git
cd AIResume
npm --prefix web ci
.\scripts\dev.ps1 web
```

Open the [local sample](http://127.0.0.1:4321/app/?demo=1) and follow the editing steps above to verify the preview. The sample needs no backend.

### Start the API

Also install Python 3.12 and uv. In another terminal, start from the repository root:

```powershell
cd api
uv sync --locked --group dev
cd ..
.\scripts\dev.ps1 api
```

The [health check](http://127.0.0.1:8010/healthz) should return `{"status":"ok"}`. See [api/.env.example](api/.env.example) for development and model settings.

Actual uploads also require a separate document processing service on Linux, LibreOffice Writer, and Noto CJK fonts; starting the API alone is not enough. Production uses Redis and keeps the document service user separate from the API user. See the [environment settings](deploy/api.env.example), [document service](deploy/airesume-pagecheck.service), and its [socket](deploy/airesume-pagecheck.socket).

### Run checks

In `web/`, run `npm run check` and `npm run build`. In `api/`, run `uv run ruff check app tests` and `uv run pytest -q`. The [acceptance workflow](.github/workflows/checks.yml) contains the complete checks and Linux integration environment.

</details>

Use fictional resume data and include reproduction steps when [reporting an issue](https://github.com/yiqi-7/AIResume/issues). The repository has no project-wide license; the bundled font is covered by the [OFL](web/public/OFL.txt).
