import json

import httpx
import pytest
from pydantic import SecretStr

from app.config import Settings
from app.documents import parse_docx
from app.llm import ModelClient, grounded
from app.metadata import Metadata
from app.schemas import Candidate, Problem, Session
from tests.test_documents import make_docx

JD = "能够进行需求分析，并将需求转化为产品原型。与设计和研发同学沟通需求。具备清晰的书面表达与协作能力。"


def sample():
    resume = parse_docx(make_docx())
    block = resume.sections[-1].blocks[0]
    candidate = Candidate(title="表达行动", priority="P1", target_block_id=block.id,
                          resume_quote=block.text, jd_quote="能够进行需求分析",
                          reason="突出已有行动", rewrite="访谈同学，整理需求，完成平台原型。")
    session = Session(id="test", auth_hash="", ip_key="hash", expires_at=9999999999,
                      resume=resume, jd=JD)
    return session, candidate


def station():
    return Settings(llm_base_url="https://model.example.invalid/v1", llm_model="test-model",
                    llm_api_key=SecretStr("test-key-not-real"))


def response(content):
    return httpx.Response(200, json={"choices": [{"message": {"content": content}}],
                                     "usage": {"prompt_tokens": 100, "completion_tokens": 50}})


def test_quotes_punctuation_and_numeric_tokens_are_not_fuzzy_matches():
    session, candidate = sample()
    assert grounded(candidate, session.resume, JD)
    assert not grounded(candidate.model_copy(update={"jd_quote": "原文未写的技能"}),
                        session.resume, JD)
    assert not grounded(candidate.model_copy(update={"rewrite": "访谈了 10 位同学"}),
                        session.resume, JD)
    assert not grounded(candidate.model_copy(update={"rewrite": "访谈了 1 位同学"}),
                        session.resume, JD, fact="访谈了 10 位同学")
    gap = candidate.model_copy(update={"needs_fact": True, "rewrite": "", "question": "怎样沟通？"})
    assert grounded(gap, session.resume, JD)
    assert not grounded(gap.model_copy(update={"rewrite": "擅长沟通"}), session.resume, JD)


async def test_json_and_grounding_failures_share_one_retry():
    session, candidate = sample()
    calls = []

    def upstream(req):
        calls.append(json.loads(req.content))
        if len(calls) == 1:
            return response("not JSON")
        invented = candidate.model_copy(update={"rewrite": "将转化率提升了 80%"})
        return response(json.dumps({"items": [candidate.model_dump(), invented.model_dump()]}))

    settings = station()
    metadata = Metadata(settings)
    client = ModelClient(settings, metadata, httpx.MockTransport(upstream))
    try:
        result = await client.dimension("content", session, client.resolve("station", "", None))
        assert len(calls) == 2 and len(result) == 1
        assert result[0].rewrite == candidate.rewrite
        assert (await metadata.stats())["dropped_ungrounded"] == 1
    finally:
        await client.close()


async def test_bad_key_is_not_retried_or_reflected():
    calls = []

    def upstream(req):
        calls.append(req)
        return httpx.Response(401, text="test-key-not-real private upstream details")

    settings = station()
    client = ModelClient(settings, Metadata(settings), httpx.MockTransport(upstream))
    session, _ = sample()
    try:
        with pytest.raises(Problem, match="MODEL_KEY_INVALID") as error:
            await client.dimension("content", session, client.resolve("station", "", None))
        assert len(calls) == 1
        assert "test-key-not-real" not in error.value.message
    finally:
        await client.close()


async def test_missing_station_and_byok_allowlist_and_fact_answer():
    settings = Settings()
    client = ModelClient(settings, Metadata(settings), httpx.MockTransport(
        lambda req: response(json.dumps({"rewrite": "整理用户反馈，与同学核对原型。"}))))
    session, candidate = sample()
    try:
        with pytest.raises(Problem, match="MODEL_NOT_CONFIGURED"):
            client.resolve("station", "", None)
        with pytest.raises(Problem, match="MODEL_KEY_REQUIRED"):
            client.resolve("https://internal.invalid", "model", "fake")
        credentials = client.resolve("deepseek", "test-model", "fake-test-key")
        text = await client.answer(session, candidate, "整理用户反馈，与同学核对原型。", credentials)
        assert text == "整理用户反馈，与同学核对原型。"
        assert "budget" not in json.dumps(client.metadata.values)
    finally:
        await client.close()
