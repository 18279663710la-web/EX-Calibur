"""Verify that removed endpoints return 404."""

import pytest
from httpx import ASGITransport, AsyncClient


@pytest.mark.anyio
async def test_auth_endpoints_gone():
    from src.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        for path in [
            "/api/v1/auth/register",
            "/api/v1/auth/login",
            "/api/v1/auth/refresh",
            "/api/v1/auth/me",
        ]:
            r = await client.post(path, json={})
            assert r.status_code == 404, f"{path} should be 404, got {r.status_code}"


@pytest.mark.anyio
async def test_file_endpoints_gone():
    from src.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        for path in [
            "/api/v1/files",
            "/api/v1/files/upload",
            "/api/v1/files/sync-from-dify",
        ]:
            r = await client.get(path)
            assert r.status_code in (404, 405), f"{path} should be 404/405, got {r.status_code}"
        r = await client.post("/api/v1/files/upload")
        assert r.status_code == 404
        r = await client.delete("/api/v1/files/any-id")
        assert r.status_code == 404
        r = await client.get("/api/v1/files/any-id/download")
        assert r.status_code == 404


@pytest.mark.anyio
async def test_dashboard_endpoints_gone():
    from src.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        for path in [
            "/api/v1/dashboard/stats",
            "/api/v1/dashboard/stats/timeline",
            "/api/v1/dashboard/stats/users",
        ]:
            r = await client.get(path)
            assert r.status_code == 404, f"{path} should be 404, got {r.status_code}"


@pytest.mark.anyio
async def test_pipeline_endpoints_gone():
    from src.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/api/v1/files/pipeline/status/any-task-id")
        assert r.status_code == 404
        r = await client.post("/api/v1/files/pipeline")
        assert r.status_code == 404


@pytest.mark.anyio
async def test_clawbot_endpoint_gone():
    from src.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.post("/api/v1/clawbot/webhook", json={})
        assert r.status_code == 404


@pytest.mark.anyio
async def test_channels_endpoints_gone():
    from src.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/api/v1/channels")
        assert r.status_code == 404
        r = await client.post("/api/v1/channels/weixin/qrlogin", json={})
        assert r.status_code == 404


@pytest.mark.anyio
async def test_conversations_crud_gone():
    from src.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        for path in [
            "/api/v1/knowledge-base/conversations",
            "/api/v1/knowledge-base/conversations/any-id",
        ]:
            r = await client.get(path)
            assert r.status_code == 404, f"{path} should be 404, got {r.status_code}"
            r = await client.delete(path)
            assert r.status_code == 404, f"{path} should be 404, got {r.status_code}"


@pytest.mark.anyio
async def test_chat_upload_endpoint_gone():
    from src.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.post("/api/v1/knowledge-base/chat/upload")
        assert r.status_code == 404
