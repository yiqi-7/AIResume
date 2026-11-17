"""Dedicated localhost-only QA fixture. Never use this app as a production entry point."""
from pathlib import Path

import httpx

from app.main import create_app
from tests.test_api import mock_model
from tests.test_llm import station

settings = station().model_copy(update={
    "data_dir": Path(__file__).resolve().parents[2] / ".local" / "qa-sessions",
    "allowed_origins": ["http://127.0.0.1:4322"],
})
app = create_app(settings, httpx.MockTransport(mock_model))
