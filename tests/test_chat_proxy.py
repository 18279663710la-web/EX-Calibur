"""Tests for the BFF proxy chat endpoint and health check."""

import json
import pytest
from httpx import ASGITransport, AsyncClient


@pytest.mark.anyio
async def test_health_endpoint_returns_200():
    from src.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"


@pytest.mark.anyio
async def test_chat_endpoint_returns_sse_stream(monkeypatch):
    from src.main import app

    class FakeResponse:
        status_code = 200

        async def aread(self):
            return b""

        async def aiter_lines(self):
            yield 'data: {"event":"text_chunk","data":{"text":"hello"}}'
            yield 'data: {"event":"workflow_finished","data":{"total_tokens":1,"elapsed_time":0.1}}'

    class FakeStream:
        def __init__(self, method, url, headers=None, content=None):
            pass

        async def __aenter__(self):
            return FakeResponse()

        async def __aexit__(self, *args):
            pass

    class FakeClient:
        def __init__(self, timeout=None):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        def stream(self, method, url, headers=None, content=None):
            return FakeStream(method, url, headers=headers, content=content)

    from src.services import dify
    monkeypatch.setattr(dify.httpx, "AsyncClient", FakeClient)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/knowledge-base/chat",
            json={"query": "hello", "model": "deepseek-v4-flash"},
        )
        assert response.status_code == 200
        assert "text/event-stream" in response.headers["content-type"]


@pytest.mark.anyio
async def test_chat_endpoint_forwards_query_to_dify(monkeypatch):
    from src.main import app

    captured_payloads = []

    class FakeResponse:
        status_code = 200

        async def aread(self):
            return b""

        async def aiter_lines(self):
            yield 'data: {"event":"workflow_finished","data":{"total_tokens":0,"elapsed_time":0}}'

    class FakeStream:
        def __init__(self, method, url, headers=None, content=None):
            if content:
                captured_payloads.append(json.loads(content.decode("utf-8")))

        async def __aenter__(self):
            return FakeResponse()

        async def __aexit__(self, *args):
            pass

    class FakeClient:
        def __init__(self, timeout=None):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        def stream(self, method, url, headers=None, content=None):
            return FakeStream(method, url, headers=headers, content=content)

    from src.services import dify
    monkeypatch.setattr(dify.httpx, "AsyncClient", FakeClient)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        await client.post(
            "/api/v1/knowledge-base/chat",
            json={
                "query": "find code in report five",
                "model": "deepseek-v4-flash",
            },
        )

    assert len(captured_payloads) == 1
    payload = captured_payloads[0]
    assert payload["inputs"]["query"] == "find code in report five"
    assert payload["response_mode"] == "streaming"
    assert "user" in payload


@pytest.mark.anyio
async def test_chat_endpoint_streams_dify_text_chunks(monkeypatch):
    from src.main import app

    class FakeResponse:
        status_code = 200

        async def aread(self):
            return b""

        async def aiter_lines(self):
            yield 'data: {"event":"text_chunk","data":{"text":"hello"}}'
            yield 'data: {"event":"text_chunk","data":{"text":"world"}}'
            yield 'data: {"event":"workflow_finished","data":{"total_tokens":2,"elapsed_time":0.1}}'

    class FakeStream:
        def __init__(self, method, url, headers=None, content=None):
            pass

        async def __aenter__(self):
            return FakeResponse()

        async def __aexit__(self, *args):
            pass

    class FakeClient:
        def __init__(self, timeout=None):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        def stream(self, method, url, headers=None, content=None):
            return FakeStream(method, url, headers=headers, content=content)

    from src.services import dify
    monkeypatch.setattr(dify.httpx, "AsyncClient", FakeClient)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/knowledge-base/chat",
            json={"query": "hello", "model": "deepseek-v4-flash"},
        )
        assert response.status_code == 200
        body = response.text
        assert "hello" in body
        assert "world" in body


@pytest.mark.anyio
async def test_chat_endpoint_forwards_dify_errors(monkeypatch):
    from src.main import app

    class FakeResponse:
        status_code = 500

        async def aread(self):
            return b'{"error":"internal"}'

        async def aiter_lines(self):
            yield ""
            return
            yield

    class FakeStream:
        def __init__(self, method, url, headers=None, content=None):
            pass

        async def __aenter__(self):
            return FakeResponse()

        async def __aexit__(self, *args):
            pass

    class FakeClient:
        def __init__(self, timeout=None):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        def stream(self, method, url, headers=None, content=None):
            return FakeStream(method, url, headers=headers, content=content)

    from src.services import dify
    monkeypatch.setattr(dify.httpx, "AsyncClient", FakeClient)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/knowledge-base/chat",
            json={"query": "hello", "model": "deepseek-v4-flash"},
        )
        assert response.status_code == 200
        body = response.text
        assert "event: error" in body


@pytest.mark.anyio
async def test_chat_endpoint_rejects_empty_query():
    from src.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/knowledge-base/chat",
            json={"query": "", "model": "deepseek-v4-flash"},
        )
        assert response.status_code == 422
