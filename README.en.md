# AIResume · 叙职

**Tailor your resume to a role, one edit at a time.** Built for students and recent graduates. Compare suggestions with the original resume and job requirements, keep the edits that reflect your experience, and download an editable Word document.

[Try the sample](https://key123456.online/app/?demo=1) · [Edit my resume](https://key123456.online/app/) · [简体中文](README.md)

## Try one edit

1. In the sample workspace, select **让个人行动更容易被看见** (make your contribution easier to see).
2. Compare the original text with the job requirements. Tick **确认改写符合我的经历** (confirm the rewrite matches my experience), then click **采纳这条修改** (accept this edit).
3. Switch to **简历预览** (resume preview) to see the revised description of the campus resale project.

The interface is primarily in Chinese. The sample uses fictional data and needs no account, upload, or model configuration. To export a DOCX, use the workspace with your own resume and job description.

## Files and privacy

- **Uploads** accept DOC, DOCX, and PDFs with selectable text, up to **5 MB and 8 pages** per file. Scans need a text layer first.
- **Exports** use a standard layout. The server starts cleaning up the session after sending the Word file. You can also clear the session from the workspace.
- **Analysis** sends resume content and the job description to the selected model provider. Use the site model, a DeepSeek key, or a custom public HTTPS API that supports OpenAI Chat Completions, OpenAI Responses, or Anthropic Messages. Custom settings are stored in your browser. [Data handling](https://key123456.online/privacy/)

## Run locally

Use Node.js 24 and PowerShell to launch the sample page.

```powershell
git clone https://github.com/yiqi-7/AIResume.git
cd AIResume
npm --prefix web ci
.\scripts\dev.ps1 web
```

Open the [local sample](http://127.0.0.1:4321/app/?demo=1). You should see the suggestion list and resume preview tabs.

To run the API, use Python 3.12 and uv. In a second terminal, start from the repository root.

```powershell
cd api
uv sync --locked --group dev
cd ..
.\scripts\dev.ps1 api
```

The [API health check](http://127.0.0.1:8010/healthz) should return `{"status":"ok"}`. See [api/.env.example](api/.env.example) for local and model settings.

## Deploy and develop

File uploads require a separate document processing service on Linux, LibreOffice Writer, and Noto CJK fonts. Production uses Redis. Keep the document service user separate from the API user. See the [production environment settings](deploy/api.env.example), [systemd service](deploy/airesume-pagecheck.service), and [socket](deploy/airesume-pagecheck.socket).

In `web/`, run `npm run check` and `npm run build`. In `api/`, run `uv run ruff check app tests` and `uv run pytest -q`. [Full acceptance workflow](.github/workflows/checks.yml)

Use fictional resume data and include reproduction steps when [reporting an issue](https://github.com/yiqi-7/AIResume/issues). The repository has no project-wide license. The bundled font is covered by the [OFL](web/public/OFL.txt).
