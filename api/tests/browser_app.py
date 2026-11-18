"""Dedicated localhost-only QA fixture. Never use this app as a production entry point."""
import json
from pathlib import Path

import httpx

from app import custom_api
from app.main import create_app
from app.pdf_documents import parse_pdf
from app.schemas import Problem
from tests.test_api import mock_model
from tests.test_llm import station

settings = station().model_copy(update={
    "data_dir": Path(__file__).resolve().parents[2] / ".local" / "qa-sessions",
    "allowed_origins": ["http://127.0.0.1:4322"],
})

def mock_extraction(request):
    if request.url.path == "/extract" and request.url.params.get("format") == "pdf":
        try:
            resume = parse_pdf(request.content)
            return httpx.Response(200, json={"pages": resume.rendered_pages,
                                             "resume": resume.model_dump()})
        except Problem as exc:
            return httpx.Response(422, json={"code": exc.code})
    return httpx.Response(200, json={"pages": 1})


async def qa_addresses(host, port):
    if host != "provider.example.invalid":
        raise Problem("MODEL_URL_UNREACHABLE", "QA only accepts the synthetic model host", 422)
    return ["93.184.216.34"]


def qa_model(request):
    if request.method == 'POST' and json.loads(request.content).get('model') == 'restricted-model':
        return httpx.Response(200, json={'choices': [{'message': {
            'content': '本站仅限主流 Coding 客户端/CLI 使用。synthetic-private-marker'}}]})
    if request.method == "GET" and request.url.path == "/v1/models":
        return httpx.Response(200, json={"data": [{"id": "gpt-6-luna"}, {"id": "test-model"}]})
    if request.url.path == "/v1/responses":
        payload = json.loads(request.content)
        adapted = httpx.Request("POST", request.url, json={"messages": payload["input"]})
        content = mock_model(adapted).json()["choices"][0]["message"]["content"]
        return httpx.Response(200, json={"status": "completed", "output": [
            {"type": "message", "content": [{"type": "output_text", "text": content}]}]})
    if request.url.path == "/v1/messages":
        payload = json.loads(request.content)
        assert request.headers["x-api-key"].startswith("synthetic-browser-key-")
        adapted = httpx.Request("POST", request.url, json={"messages": [
            {"role": "system", "content": payload["system"]}, *payload["messages"]]})
        content = mock_model(adapted).json()["choices"][0]["message"]["content"]
        return httpx.Response(200, json={"stop_reason": "end_turn", "content": [
            {"type": "text", "text": content}]})
    return mock_model(request)


custom_api.public_addresses = qa_addresses


# Browser QA exercises editing with synthetic material. The Linux service has separate integration tests.
app = create_app(settings, httpx.MockTransport(qa_model),
                 httpx.MockTransport(mock_extraction))
