"""Dedicated localhost-only QA fixture. Never use this app as a production entry point."""
from pathlib import Path

import httpx

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


# Browser QA exercises editing with synthetic material. The Linux service has separate integration tests.
app = create_app(settings, httpx.MockTransport(mock_model),
                 httpx.MockTransport(mock_extraction))
