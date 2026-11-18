"""Local browser QA against a real API and a mocked model; never calls a cloud model.

Run npm run build in web first. Requires: python -m pip install playwright python-docx
Chrome is used from its local installation; no Playwright browser download is required.
"""
import http.client
import json
import os
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / ".local" / "qa"
CHROME = Path(os.environ.get("BROWSER_QA_CHROME") or shutil.which("google-chrome") or
              r"C:\Program Files\Google\Chrome\Application\chrome.exe")


class StaticQAHandler(SimpleHTTPRequestHandler):
    """Loopback-only fixture serving built pages and proxying only the dedicated test API."""

    extensions_map = {
        **SimpleHTTPRequestHandler.extensions_map,
        ".js": "application/javascript",
        ".mjs": "application/javascript",
        ".css": "text/css",
        ".woff2": "font/woff2",
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT / "web" / "dist"), **kwargs)

    def log_message(self, *args):
        pass

    def do_GET(self):
        if urlsplit(self.path).path.startswith("/api/"):
            self.proxy()
        else:
            super().do_GET()

    def proxy(self):
        if not urlsplit(self.path).path.startswith("/api/"):
            self.send_error(404)
            return
        length = int(self.headers.get("Content-Length", "0"))
        connection = http.client.HTTPConnection("127.0.0.1", 8011, timeout=30)
        try:
            headers = {key: value for key, value in self.headers.items()
                       if key.lower() not in {"connection", "host", "transfer-encoding"}}
            connection.request(self.command, self.path, self.rfile.read(length), headers)
            response = connection.getresponse()
            content = response.read()
            self.send_response(response.status)
            for key, value in response.getheaders():
                if key.lower() not in {"connection", "transfer-encoding", "content-length"}:
                    self.send_header(key, value)
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)
        finally:
            connection.close()

    do_POST = do_PATCH = do_DELETE = proxy


def ready(url):
    for _ in range(120):
        try:
            with urllib.request.urlopen(url, timeout=1) as response:
                if response.status == 200:
                    return
        except Exception:
            time.sleep(0.5)
    raise RuntimeError(f"Local server did not start: {url}")


def main():
    if not (ROOT / "web" / "dist" / "app" / "index.html").is_file():
        raise RuntimeError("Run npm run build in web before browser QA")
    OUT.mkdir(parents=True, exist_ok=True)
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    api_python = ROOT / "api" / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    # One dedicated directory and ports; ordinary development sessions remain untouched.
    processes = []
    handles = []
    server = None
    try:
        for name, command, cwd in [
            ("api", [str(api_python), "-m", "uvicorn", "tests.browser_app:app", "--host", "127.0.0.1", "--port", "8011"], ROOT / "api"),
        ]:
            log = (OUT / f"{name}.log").open("w", encoding="utf-8")
            handles.append(log)
            processes.append(subprocess.Popen(command, cwd=cwd, env=os.environ, stdout=log,
                                               stderr=log, creationflags=flags))
        ready("http://127.0.0.1:8011/healthz")
        server = ThreadingHTTPServer(("127.0.0.1", 4322), StaticQAHandler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        ready("http://127.0.0.1:4322/")
        with urllib.request.urlopen("http://127.0.0.1:4322/api/config", timeout=5) as response:
            assert "application/json" in response.headers["Content-Type"]
        with sync_playwright() as p:
            browser = p.chromium.launch(executable_path=str(CHROME), headless=True)
            context = browser.new_context(viewport={"width": 1440, "height": 1050})
            page = context.new_page()
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))

            def capture(name):
                page.evaluate("document.fonts.ready")
                assert page.evaluate("document.fonts.check('14px \"Noto Sans SC Variable\"', '简历')")
                assert page.evaluate("[...document.fonts].some(f=>f.family.includes('Noto Sans SC') && f.status==='loaded')")
                assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 1"), name
                page.screenshot(path=str(OUT / f"{name}.png"), full_page=True)

            page.goto("http://127.0.0.1:4322/", wait_until="networkidle")
            capture("landing-desktop")
            page.set_viewport_size({"width": 390, "height": 844})
            capture("landing-mobile")
            page.goto("http://127.0.0.1:4322/app/?demo=1", wait_until="networkidle")
            expect(page.get_by_role("heading", name="从一条具体的修改开始。" )).to_be_visible()
            capture("review-mobile")
            page.set_viewport_size({"width": 1440, "height": 1050})
            capture("review-desktop")
            page.get_by_role("button", name="模型设置").click()
            expect(page.get_by_role("dialog")).to_be_visible()
            page.keyboard.press("Escape")
            expect(page.get_by_role("dialog")).not_to_be_visible()

            page.goto("http://127.0.0.1:4322/app/", wait_until="networkidle")
            capture("upload-desktop")
            sys.path.insert(0, str(ROOT / "api"))
            from tests.test_documents import make_textbox_docx
            from tests.test_pdf_documents import make_pdf

            sample = OUT / "fictional.docx"
            sample.write_bytes(make_textbox_docx())
            page.get_by_label("选择 Word 或 PDF 简历").set_input_files(str(sample))
            page.get_by_label("目标岗位描述").fill("能够进行需求分析，并将需求转化为产品原型。与设计和研发同学沟通需求。具备清晰的书面表达与协作能力。")
            page.get_by_role("checkbox").check()
            page.get_by_role("button", name="读取简历", exact=True).click()
            expect(page.get_by_role("heading", name="先确认，读对了没有。")).to_be_visible()
            expect(page.get_by_text("陈测试 · fictional@example.invalid", exact=True)).to_be_visible()
            capture("parsed-desktop")
            page.get_by_role("button", name="读取无误，开始分析").click()
            expect(page.get_by_role("heading", name="从一条具体的修改开始。")).to_be_visible(timeout=20000)
            page.get_by_role("button", name="写清个人行动").click()
            page.get_by_label("建议改写", exact=True).fill("访谈同学，整理需求并完成原型。")
            page.get_by_role("checkbox").check()
            page.get_by_role("button", name="采纳这条修改").click()
            expect(page.get_by_text("已采纳 1 条", exact=True)).to_be_visible()
            capture("accepted-desktop")
            page.get_by_role("button", name="待处理", exact=True).click()
            expect(page.get_by_role("heading", name="写清个人行动", exact=True)).not_to_be_visible()
            page.get_by_role("button", name="补充真实沟通经历").click()
            page.get_by_role("button", name="跳过这条", exact=True).click()
            expect(page.get_by_text("这个分类暂时没有建议。", exact=True)).to_be_visible()
            expect(page.get_by_role("region", name="当前修改建议")).to_have_count(0)
            page.get_by_role("button", name="已跳过", exact=True).click()
            page.get_by_role("button", name="撤销选择", exact=True).click()
            expect(page.get_by_text("这个分类暂时没有建议。", exact=True)).to_be_visible()
            page.get_by_role("button", name="待处理", exact=True).click()
            page.get_by_label("你怎样和同学沟通需求？").fill("和同学核对需求文档。")
            page.get_by_role("checkbox").check()
            page.get_by_role("button", name="根据补充生成改写").click()
            expect(page.get_by_label("建议改写", exact=True)).to_have_value("和同学核对需求文档。", timeout=20000)
            page.get_by_role("checkbox").check()
            page.get_by_role("button", name="采纳这条修改").click()
            expect(page.get_by_text("已采纳 2 条", exact=True)).to_be_visible()
            page.get_by_role("button", name="简历预览", exact=True).click()
            expect(page.get_by_role("article")).to_be_visible()
            page.get_by_role("button", name="实际尺寸").click()
            assert not page.locator(".preview-scroll").evaluate("e=>e.scrollWidth > e.clientWidth")
            page.get_by_role("button", name="适合屏幕").click()
            capture("preview-desktop")
            page.set_viewport_size({"width": 390, "height": 844})
            capture("preview-mobile")
            page.get_by_role("button", name="实际尺寸").click()
            assert page.locator(".preview-scroll").evaluate("e=>e.scrollWidth > e.clientWidth")
            capture("preview-mobile-actual")
            page.get_by_role("button", name="适合屏幕").click()
            page.get_by_role("button", name="导出 Word", exact=True).click()
            with page.expect_download() as downloaded:
                page.get_by_role("button", name="确认导出 Word", exact=True).click()
            downloaded.value.save_as(str(OUT / "exported.docx"))
            expect(page.get_by_text("下载已发起", exact=False)).to_be_visible()
            expect(page.get_by_role("heading", name="先放入你的简历。")).to_be_visible()
            assert page.request.get("http://127.0.0.1:4322/api/session").json()["session"] is None
            pdf = OUT / "fictional.pdf"
            pdf.write_bytes(make_pdf())
            page.get_by_label("选择 Word 或 PDF 简历").set_input_files(str(pdf))
            page.get_by_label("目标岗位描述").fill("能够进行需求分析，并将需求转化为产品原型。与设计和研发同学沟通需求。具备清晰的书面表达与协作能力。")
            page.get_by_role("checkbox").check()
            page.get_by_role("button", name="读取简历", exact=True).click()
            expect(page.get_by_role("heading", name="先确认，读对了没有。")).to_be_visible()
            expect(page.get_by_text("Fictional Candidate - 2024 - fictional@example.invalid", exact=True)).to_be_visible()
            capture("pdf-parsed-mobile")
            page.get_by_role("button", name="结束会话", exact=True).click()
            page.get_by_role("button", name="确认结束", exact=True).click()
            expect(page.get_by_role("heading", name="先放入你的简历。")).to_be_visible()
            # Three persistent custom profiles, catalog/manual models, both protocols,
            # editing/deletion and a real UI -> API -> mocked upstream analysis.
            page.set_viewport_size({"width": 1440, "height": 1050})
            expect(page.locator('.current-model')).to_contain_text('test-model')
            page.get_by_role('button', name='模型设置').click()
            expect(page.locator('.station-model-info')).to_contain_text('test-model')
            expect(page.locator('.station-model-info')).to_contain_text('OpenAI Chat Completions')
            capture('station-model-visible')
            page.get_by_role('button', name='关闭模型设置', exact=True).click()
            for index in range(1, 4):
                page.get_by_role("button", name="模型设置").click()
                page.get_by_role("tab", name="自定义模型 API").click()
                page.get_by_role("button", name="添加自定义 API", exact=True).click()
                page.get_by_label("Provider ID", exact=True).fill(f"custom-{index}")
                page.get_by_label("显示名称", exact=True).fill(f"虚构服务 {index}")
                page.get_by_label("API 地址", exact=True).fill("https://provider.example.invalid/v1")
                page.get_by_label("API Key", exact=True).fill(f"synthetic-browser-key-{index}")
                if index == 2:
                    page.get_by_label("添加模型 ID", exact=True).fill("gpt-6-luna")
                    page.get_by_role("button", name="添加模型", exact=True).click()
                else:
                    page.get_by_role("button", name="获取可用模型", exact=True).click()
                    expect(page.get_by_text("已获取 2 个模型", exact=False)).to_be_visible()
                if index == 3:
                    page.get_by_label("API 协议", exact=True).select_option("anthropic_messages")
                    page.set_viewport_size({"width": 390, "height": 844})
                if index == 1:
                    expect(page.locator('.model-chips>span')).to_have_count(2)
                    page.get_by_role('button', name='设为默认模型 test-model', exact=True).click()
                    expect(page.get_by_label('默认模型 ID', exact=True)).to_have_value('test-model')
                capture(f"custom-api-editor-{'mobile' if index == 3 else 'desktop'}")
                page.get_by_role("button", name="创建并使用", exact=True).click()
                expect(page.get_by_role("dialog")).not_to_be_visible()
            page.reload(wait_until="networkidle")
            page.get_by_role("button", name="模型设置").click()
            expect(page.get_by_role("tab", name="自定义模型 API")).to_have_attribute("aria-selected", "true")
            expect(page.locator(".custom-api-card")).to_have_count(3)
            third = page.locator('.custom-api-card').filter(has=page.get_by_role('heading', name='虚构服务 3', exact=True))
            third.get_by_label('本次使用的模型 · 虚构服务 3', exact=True).fill('test-model')
            third.get_by_role('button', name='使用', exact=True).click()
            page.reload(wait_until='networkidle')
            expect(page.locator('.current-model')).to_contain_text('test-model')
            # This uses a catalog model without replacing the profile's default.
            assert page.evaluate("JSON.parse(localStorage.getItem('airesume-custom-apis-v1')).find(p=>p.id==='custom-3').model") == 'gpt-6-luna'
            page.get_by_label('选择 Word 或 PDF 简历').set_input_files(str(sample))
            page.get_by_label('目标岗位描述').fill('能够进行需求分析，并将需求转化为产品原型。与设计和研发同学沟通需求。具备清晰的书面表达与协作能力。')
            page.get_by_role('checkbox').check()
            page.get_by_role('button', name='读取简历', exact=True).click()
            expect(page.get_by_role('heading', name='先确认，读对了没有。')).to_be_visible()
            with page.expect_request(lambda req:req.url.endswith('/analyze')) as anthropic:
                page.get_by_role('button', name='读取无误，开始分析').click()
            assert anthropic.value.post_data_json['protocol'] == 'anthropic_messages'
            assert anthropic.value.post_data_json['model'] == 'test-model'
            expect(page.get_by_role('heading', name='从一条具体的修改开始。')).to_be_visible(timeout=20000)
            page.get_by_role('button', name='结束会话', exact=True).click()
            page.get_by_role('button', name='确认结束', exact=True).click()
            expect(page.get_by_role('heading', name='先放入你的简历。')).to_be_visible()
            page.get_by_role('button', name='模型设置').click()
            expect(page.get_by_role("button", name="添加自定义 API", exact=True)).to_be_disabled()
            capture("custom-api-limit-mobile")
            restricted = page.locator('.custom-api-card').filter(has=page.get_by_role('heading', name='虚构服务 1', exact=True))
            restricted.get_by_label('本次使用的模型 · 虚构服务 1', exact=True).fill('restricted-model')
            restricted.get_by_role('button', name='使用', exact=True).click()
            page.get_by_label('选择 Word 或 PDF 简历').set_input_files(str(sample))
            page.get_by_label('目标岗位描述').fill('能够进行需求分析，并将需求转化为产品原型。与设计和研发同学沟通需求。具备清晰的书面表达与协作能力。')
            page.get_by_role('checkbox').check()
            page.get_by_role('button', name='读取简历', exact=True).click()
            expect(page.get_by_role('heading', name='先确认，读对了没有。')).to_be_visible()
            page.get_by_role('button', name='读取无误，开始分析').click()
            expect(page.get_by_role('heading', name='这次分析没有完成')).to_be_visible(timeout=20000)
            expect(page.locator('.analysis-failure')).to_contain_text('拒绝网页应用调用')
            expect(page.locator('.analysis-failure')).not_to_contain_text('synthetic-private-marker')
            capture('model-restriction-actionable-error')
            page.get_by_role('button', name='结束会话', exact=True).click()
            page.get_by_role('button', name='确认结束', exact=True).click()
            expect(page.get_by_role('heading', name='先放入你的简历。')).to_be_visible()
            page.get_by_role('button', name='模型设置').click()
            card = page.locator(".custom-api-card").filter(has=page.get_by_role("heading", name="虚构服务 2", exact=True))
            card.get_by_role("button", name="编辑", exact=True).click()
            expect(page.get_by_label("Provider ID", exact=True)).to_be_disabled()
            page.get_by_label("显示名称", exact=True).fill("虚构服务 2 已更新")
            page.get_by_label("API 协议", exact=True).select_option("responses")
            page.get_by_role("button", name="保存并使用", exact=True).click()
            page.get_by_role("button", name="模型设置").click()
            expect(page.get_by_role("heading", name="虚构服务 2 已更新", exact=True)).to_be_visible()
            page.get_by_role("button", name="删除 虚构服务 1", exact=True).click()
            expect(page.locator(".custom-api-card")).to_have_count(2)
            expect(page.get_by_role("button", name="添加自定义 API", exact=True)).to_be_enabled()
            page.get_by_role("button", name="完成", exact=True).click()
            # Reload proves the active profile, address, protocol and Key are restored.
            page.reload(wait_until="networkidle")
            page.get_by_label("选择 Word 或 PDF 简历").set_input_files(str(sample))
            page.get_by_label("目标岗位描述").fill("能够进行需求分析，并将需求转化为产品原型。与设计和研发同学沟通需求。具备清晰的书面表达与协作能力。")
            page.get_by_role("checkbox").check()
            page.get_by_role("button", name="读取简历", exact=True).click()
            expect(page.get_by_role("heading", name="先确认，读对了没有。")).to_be_visible()
            with page.expect_request(lambda req: req.url.endswith("/analyze")) as submitted:
                page.get_by_role("button", name="读取无误，开始分析").click()
            assert submitted.value.post_data_json["provider"] == "custom"
            assert submitted.value.post_data_json["protocol"] == "responses"
            assert submitted.value.post_data_json["base_url"] == "https://provider.example.invalid/v1"
            assert submitted.value.headers["x-llm-key"] == "synthetic-browser-key-2"
            expect(page.get_by_role("heading", name="从一条具体的修改开始。")).to_be_visible(timeout=20000)
            page.get_by_role("button", name="结束会话", exact=True).click()
            page.get_by_role("button", name="确认结束", exact=True).click()
            expect(page.get_by_role("heading", name="先放入你的简历。")).to_be_visible()
            assert page.evaluate("JSON.parse(localStorage.getItem('airesume-custom-apis-v1')).length") == 2
            page.get_by_role("button", name="模型设置").click()
            page.get_by_role("button", name="清空全部 Key", exact=True).click()
            assert page.evaluate("localStorage.getItem('airesume-custom-apis-v1')") is None
            assert page.evaluate("localStorage.getItem('airesume-model-v1')") is None
            page.get_by_role("button", name="关闭模型设置", exact=True).click()
            assert not any((ROOT / ".local" / "qa-sessions").iterdir())
            assert errors == [], errors
            context.close()
            browser.close()
        print(json.dumps({"result": "passed", "model": "mocked upstream only", "artifacts": str(OUT)}, ensure_ascii=False))
    finally:
        if server:
            server.shutdown()
            server.server_close()
        for process in processes:
            process.terminate()
        for process in processes:
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
        for handle in handles:
            handle.close()


if __name__ == "__main__":
    main()
