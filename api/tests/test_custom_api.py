import asyncio
import gzip
import json
import ssl
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

from app import custom_api
from app.custom_api import PublicAPITransport, validate_base_url
from app.llm import ModelClient
from app.main import create_app
from app.metadata import Metadata
from app.schemas import Problem
from tests.test_api import HEADERS, mock_model, upload, wait_ready
from tests.test_llm import response, sample, station

BASE = "https://provider.example.invalid/v1"
KEY = "synthetic-private-key"


@pytest.fixture
def public_dns(monkeypatch):
    async def addresses(host, port):
        return ["93.184.216.34"]

    monkeypatch.setattr(custom_api, "public_addresses", addresses)


@pytest.mark.parametrize(
    "url",
    [
        "http://example.com/v1",
        "https://127.0.0.1/v1",
        "https://10.0.0.1",
        "https://169.254.169.254",
        "https://[::1]",
        "https://[::ffff:127.0.0.1]",
        "https://[2002:7f00:1::]",
        "https://[64:ff9b::7f00:1]",
        "https://localhost",
        "https://test.local",
        "https://user:pass@example.com",
        "https://example.com/?key=secret",
        "https://example.com/#secret",
        "https://example.com:0",
        "https://example.com:99999",
        "https://example.com\\@127.0.0.1",
        "https://example.com/with space",
    ],
)
def test_invalid_custom_urls_fail_before_network(url):
    with pytest.raises(Problem, match="MODEL_URL_INVALID"):
        validate_base_url(url)


@pytest.mark.parametrize(
    "records", [["127.0.0.1"], ["93.184.216.34", "10.0.0.7"], ["::ffff:169.254.169.254"]]
)
async def test_dns_answers_containing_private_addresses_are_blocked(monkeypatch, records):
    async def resolve(*args, **kwargs):
        return [(2, 1, 6, "", (address, 443)) for address in records]

    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", resolve)
    with pytest.raises(Problem, match="MODEL_URL_UNREACHABLE"):
        await custom_api.public_addresses("provider.example.invalid", 443)


async def test_connection_uses_validated_ip_and_preserves_host_and_tls_name(public_dns):
    calls = []

    def remote(request):
        calls.append(request)
        return httpx.Response(200, json={"data": []})

    async with httpx.AsyncClient(
        transport=PublicAPITransport(httpx.MockTransport(remote))
    ) as client:
        await client.get(BASE + "/models")
    assert len(calls) == 1
    assert calls[0].url.host == "93.184.216.34"
    assert calls[0].url.path == "/v1/models"
    assert calls[0].headers["host"] == "provider.example.invalid"
    assert calls[0].extensions["sni_hostname"] == "provider.example.invalid"


async def test_pinned_connection_verifies_certificate_for_original_hostname(tmp_path, monkeypatch):
    hostname = "provider.example.invalid"
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, hostname)])
    now = datetime.now(UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=1))
        .not_valid_after(now + timedelta(days=1))
        .add_extension(x509.SubjectAlternativeName([x509.DNSName(hostname)]), critical=False)
        .sign(key, hashes.SHA256())
    )
    cert_file, key_file = tmp_path / "cert.pem", tmp_path / "key.pem"
    cert_file.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_file.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    server_ssl = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    server_ssl.load_cert_chain(cert_file, key_file)
    sni, requests = [], []
    server_ssl.set_servername_callback(lambda socket, name, context: sni.append(name))

    async def serve(reader, writer):
        requests.append(await reader.readuntil(b"\r\n\r\n"))
        writer.write(
            b'HTTP/1.1 200 OK\r\nContent-Length: 11\r\nConnection: close\r\n\r\n{"data":[]}'
        )
        await writer.drain()
        writer.close()
        await writer.wait_closed()

    async def loopback_for_test(host, port):
        assert host == hostname
        return ["127.0.0.1"]

    monkeypatch.setattr(custom_api, "public_addresses", loopback_for_test)
    server = await asyncio.start_server(serve, "127.0.0.1", 0, ssl=server_ssl)
    port = server.sockets[0].getsockname()[1]
    context = ssl.create_default_context(cafile=str(cert_file))
    transport = httpx.AsyncHTTPTransport(
        verify=context, trust_env=False, limits=httpx.Limits(max_keepalive_connections=0)
    )
    try:
        async with httpx.AsyncClient(transport=PublicAPITransport(transport)) as client:
            result = await client.get(f"https://{hostname}:{port}/v1/models")
            assert result.json() == {"data": []}
        assert sni == [hostname]
        assert f"Host: {hostname}:{port}".encode() in requests[0]
    finally:
        server.close()
        await server.wait_closed()


@pytest.mark.parametrize("protocol", ["chat_completions", "responses", "anthropic_messages"])
async def test_custom_protocols_preserve_json_grounding_and_byok_accounting(public_dns, protocol):
    settings = station()
    metadata = Metadata(settings)
    session, candidate = sample()
    calls = []

    def upstream(request):
        calls.append(request)
        payload = json.loads(request.content)
        if protocol == "anthropic_messages":
            assert request.headers["x-api-key"] == KEY
            assert request.headers["anthropic-version"] == "2023-06-01"
            assert "authorization" not in request.headers
        else:
            assert request.headers["Authorization"] == "Bearer " + KEY
        content = json.dumps({"items": [candidate.model_dump()]})
        if protocol == "responses":
            assert request.url.path == "/v1/responses"
            assert payload["store"] is False and payload["stream"] is False
            assert "input" in payload and "messages" not in payload and "max_tokens" not in payload
            return httpx.Response(
                200,
                json={
                    "status": "completed",
                    "output": [
                        {"type": "message", "content": [{"type": "output_text", "text": content}]}
                    ],
                    "usage": {"input_tokens": 100, "output_tokens": 50},
                },
            )
        if protocol == "anthropic_messages":
            assert request.url.path == "/v1/messages"
            assert isinstance(payload["system"], str) and payload["system"]
            assert payload["messages"][0]["role"] == "user"
            assert "response_format" not in payload and "input" not in payload
            return httpx.Response(200, json={"stop_reason": "end_turn", "content": [
                {"type": "text", "text": content}],
                "usage": {"input_tokens": 100, "output_tokens": 50}})
        assert request.url.path == "/v1/chat/completions" and "messages" in payload
        return response(content)

    client = ModelClient(settings, metadata, httpx.MockTransport(upstream))
    try:
        credentials = client.resolve("custom", "test-model", KEY, BASE, protocol)
        result = await client.dimension("content", session, credentials)
        assert len(result) == 1 and result[0].rewrite == candidate.rewrite
        assert len(calls) == 1
        stats = await metadata.stats()
        assert stats["byok_prompt_tokens"] == 100 and stats["byok_completion_tokens"] == 50
        assert "budget" not in json.dumps(metadata.values)
    finally:
        await client.close()


@pytest.mark.parametrize("status", [302, 401, 500])
async def test_catalog_errors_do_not_reflect_secrets_or_follow_redirects(public_dns, status):
    calls = []

    def upstream(request):
        calls.append(request)
        return httpx.Response(
            status, text=KEY + " private detail", headers={"Location": "https://127.0.0.1"}
        )

    settings = station()
    client = ModelClient(settings, Metadata(settings), httpx.MockTransport(upstream))
    try:
        with pytest.raises(Problem) as error:
            await client.models(client.resolve("custom", "catalog", KEY, BASE))
        assert KEY not in error.value.message and len(calls) == 1
    finally:
        await client.close()


async def test_anthropic_catalog_uses_version_and_api_key_without_bearer(public_dns):
    def upstream(request):
        assert request.url.path == "/v1/models"
        assert request.headers["x-api-key"] == KEY
        assert request.headers["anthropic-version"] == "2023-06-01"
        assert "authorization" not in request.headers
        return httpx.Response(200, json={"data": [{"id": "claude-synthetic"}, {"id": "other-model"}]})

    settings = station()
    client = ModelClient(settings, Metadata(settings), httpx.MockTransport(upstream))
    try:
        credentials = client.resolve("custom", "catalog", KEY, BASE, "anthropic_messages")
        assert await client.models(credentials) == ["claude-synthetic", "other-model"]
    finally:
        await client.close()


@pytest.mark.parametrize("operation", ["catalog", "analysis"])
async def test_compressed_response_is_rejected_before_decompression(public_dns, operation):
    compressed = gzip.compress(b"x" * (16 * 1024 * 1024))
    iterations = []

    class Bomb(httpx.AsyncByteStream):
        async def __aiter__(self):
            iterations.append(True)
            yield compressed

    def upstream(request):
        assert request.headers["Accept-Encoding"] == "identity"
        return httpx.Response(200, headers={"Content-Encoding": "gzip"}, stream=Bomb())

    settings = station()
    client = ModelClient(settings, Metadata(settings), httpx.MockTransport(upstream))
    credentials = client.resolve("custom", "test-model", KEY, BASE)
    try:
        with pytest.raises(Problem):
            if operation == "catalog":
                await client.models(credentials)
            else:
                session, _ = sample()
                await client.dimension("content", session, credentials)
        assert not iterations, "Compressed body must never enter the decoder"
    finally:
        await client.close()


async def test_model_catalog_and_analysis_do_not_store_custom_configuration(tmp_path, public_dns):
    calls = []

    def upstream(request):
        calls.append(request)
        if request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "data": [
                        {"id": "synthetic-model"},
                        {"id": "synthetic-model"},
                        {"id": "bad model"},
                        {"id": 7},
                    ]
                },
            )
        return mock_model(request)

    settings = station().model_copy(update={"data_dir": tmp_path / "private"})
    app = create_app(
        settings,
        httpx.MockTransport(upstream),
        httpx.MockTransport(lambda r: httpx.Response(200, json={"pages": 1})),
    )
    payload = {
        "provider": "custom",
        "base_url": BASE,
        "protocol": "chat_completions",
        "model": "synthetic-model",
    }
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test", headers=HEADERS
        ) as c:
            catalog = await c.post("/api/models", headers={"X-LLM-Key": KEY}, json=payload)
            assert catalog.json() == {"models": ["synthetic-model"]}
            session = await upload(c)
            sid = session["id"]
            assert (
                await c.post(
                    f"/api/sessions/{sid}/analyze", headers={"X-LLM-Key": KEY}, json=payload
                )
            ).status_code == 202
            result = await wait_ready(c, sid)
            assert result["state"] == "ready"
            stored = app.state.store._read_private(app.state.store.directory(sid) / "session.json")
            assert KEY.encode() not in stored and BASE.encode() not in stored
            assert KEY not in json.dumps(result) and BASE not in json.dumps(result)
            assert len(calls) == 4
            assert (await c.delete(f"/api/sessions/{sid}")).status_code == 204


async def test_api_rejects_private_custom_url_without_creating_model_job(tmp_path):
    settings = station().model_copy(update={"data_dir": tmp_path / "private"})
    app = create_app(
        settings,
        httpx.MockTransport(lambda r: pytest.fail("must not make request")),
        httpx.MockTransport(lambda r: httpx.Response(200, json={"pages": 1})),
    )
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test", headers=HEADERS
        ) as c:
            sid = (await upload(c))["id"]
            result = await c.post(
                f"/api/sessions/{sid}/analyze",
                headers={"X-LLM-Key": KEY},
                json={"provider": "custom", "model": "test", "base_url": "https://10.4.0.7"},
            )
            assert result.status_code == 422 and result.json()["code"] == "MODEL_URL_INVALID"
            assert not app.state.store.jobs
            await c.delete(f"/api/sessions/{sid}")
