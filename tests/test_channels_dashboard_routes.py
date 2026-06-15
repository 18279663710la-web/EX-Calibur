import asyncio
import json
from datetime import date


def test_channels_list_returns_frontend_contract():
    async def run():
        from src.routes.channels import list_channels
        from src.services.channels import ChannelManager

        manager = ChannelManager()
        await manager.startup()

        response = await list_channels(manager=manager)

        assert response["code"] == 200
        channels = response["data"]["channels"]
        assert channels
        assert channels[0]["name"] == "weixin"
        assert channels[0]["label"] == "WeChat"
        assert channels[0]["label_i18n"]["zh"]
        assert {"name", "label", "running", "connected", "status"} <= set(channels[0])

    asyncio.run(run())


def test_channels_connect_weixin_returns_qr_payload():
    async def run():
        from src.routes.channels import ChannelActionRequest, change_channel_state
        from src.services.channels import ChannelManager

        class FakeWeixinClient:
            def __init__(self):
                self.calls = []

            async def get_bot_qrcode(self, bot_type=3):
                self.calls.append(("get_bot_qrcode", bot_type))
                return {
                    "qrcode": "official-qrcode-id",
                    "qrcode_img_content": "weixin://official-login-ticket",
                    "qrcode_url": "https://novac2c.cdn.weixin.qq.com/c2c/bad-ticket",
                }

        client = FakeWeixinClient()
        manager = ChannelManager(weixin_client=client, credentials_path="")
        await manager.startup()

        response = await change_channel_state(
            ChannelActionRequest(channel="weixin", action="connect"),
            manager=manager,
        )

        assert response["code"] == 200
        assert response["data"]["status"] == "pending"
        assert response["data"]["qr_status"] == "pending"
        assert response["data"]["qrcode_url"] == "weixin://official-login-ticket"
        assert response["data"]["qr_image"].startswith("data:image/png;base64,")
        assert client.calls == [("get_bot_qrcode", 3)]

    asyncio.run(run())


def test_channels_weixin_poll_confirms_and_persists_credentials(tmp_path):
    async def run():
        from src.routes.channels import QrLoginRequest, qr_login
        from src.services.channels import ChannelManager

        class FakeWeixinClient:
            async def get_bot_qrcode(self, bot_type=3):
                return {
                    "data": {
                        "qrcode": "official-qrcode-id",
                        "qrcode_img_content": "weixin://official-login-ticket",
                        "url": "https://novac2c.cdn.weixin.qq.com/c2c/bad-ticket",
                    }
                }

            async def get_qrcode_status(self, qrcode):
                return {
                    "status": "confirmed",
                    "bot_token": "bot-token-123",
                    "baseurl": "https://bot.example.com",
                    "ilink_bot_id": "bot-1",
                    "ilink_user_id": "user-1",
                }

        credentials_path = tmp_path / "weixin_credentials.json"
        manager = ChannelManager(
            weixin_client=FakeWeixinClient(),
            credentials_path=str(credentials_path),
        )
        await manager.startup()

        await qr_login(QrLoginRequest(action="fetch"), manager=manager)
        response = await qr_login(QrLoginRequest(action="poll"), manager=manager)

        assert response["code"] == 200
        assert response["data"]["status"] == "connected"
        assert response["data"]["qr_status"] == "confirmed"
        credentials = json.loads(credentials_path.read_text(encoding="utf-8"))
        assert credentials["token"] == "bot-token-123"
        assert credentials["base_url"] == "https://bot.example.com"
        assert credentials["bot_id"] == "bot-1"
        assert credentials["user_id"] == "user-1"

    asyncio.run(run())


def test_channels_weixin_poll_timeout_keeps_waiting(tmp_path):
    async def run():
        import httpx

        from src.routes.channels import QrLoginRequest, qr_login
        from src.services.channels import ChannelManager

        class FakeWeixinClient:
            async def get_bot_qrcode(self, bot_type=3):
                return {
                    "qrcode": "official-qrcode-id",
                    "qrcode_img_content": "weixin://official-login-ticket",
                }

            async def get_qrcode_status(self, qrcode):
                raise httpx.ReadTimeout("no scan yet")

        manager = ChannelManager(
            weixin_client=FakeWeixinClient(),
            credentials_path=str(tmp_path / "weixin_credentials.json"),
        )
        await manager.startup()

        await qr_login(QrLoginRequest(action="fetch"), manager=manager)
        response = await qr_login(QrLoginRequest(action="poll"), manager=manager)

        assert response["code"] == 200
        assert response["data"]["status"] == "pending"
        assert response["data"]["qr_status"] == "pending"

    asyncio.run(run())


def test_dashboard_stats_matches_frontend_contract(monkeypatch):
    async def run():
        from src.routes import dashboard

        class FakePool:
            async def fetchrow(self, query, *args):
                normalized = " ".join(query.split())
                if "FROM conversations c" in normalized:
                    return {
                        "total_conversations": 2,
                        "avg_tokens_per_conversation": 150,
                    }
                if "FROM messages m" in normalized:
                    return {
                        "total_messages": 4,
                        "input_tokens": 100,
                        "output_tokens": 200,
                        "total_tokens": 300,
                        "avg_latency_ms": 125,
                        "p50_latency_ms": 100,
                        "p95_latency_ms": 190,
                        "p99_latency_ms": 198,
                        "max_latency_ms": 200,
                        "min_latency_ms": 50,
                    }
                if "FROM file_metadata" in normalized:
                    return {
                        "total_files_uploaded": 3,
                        "total_storage_bytes": 2048,
                    }
                if "FROM operation_logs" in normalized:
                    return {"active_users": 2}
                raise AssertionError(f"unexpected query: {normalized}")

            async def fetch(self, query, *args):
                return [
                    {"model": "gpt-4o", "call_count": 2, "total_tokens": 300, "avg_latency_ms": 125}
                ]

        async def fake_get_pool():
            return FakePool()

        monkeypatch.setattr(dashboard, "get_pool", fake_get_pool)

        response = await dashboard.stats(
            start_date=date(2026, 6, 1),
            end_date=date(2026, 6, 9),
            current_user={"role": "admin"},
        )

        assert response["code"] == 200
        data = response["data"]
        assert data["summary"]["total_conversations"] == 2
        assert data["summary"]["total_storage_human"] == "2.00 KB"
        assert data["token_consumption"]["total_tokens_human"] == "300"
        assert data["latency"]["p95_latency_ms"] == 190
        assert data["model_breakdown"][0]["model"] == "gpt-4o"

    asyncio.run(run())


def test_dashboard_timeline_fills_missing_days(monkeypatch):
    async def run():
        from src.routes import dashboard

        class FakePool:
            async def fetch(self, query, *args):
                return [
                    {
                        "date": date(2026, 6, 1),
                        "conversations": 1,
                        "messages": 2,
                        "tokens_used": 30,
                        "avg_latency_ms": 40,
                        "files_uploaded": 1,
                        "active_users": 1,
                        "errors_count": 0,
                    }
                ]

        async def fake_get_pool():
            return FakePool()

        monkeypatch.setattr(dashboard, "get_pool", fake_get_pool)

        response = await dashboard.timeline(
            start_date=date(2026, 6, 1),
            end_date=date(2026, 6, 3),
            granularity="daily",
            current_user={"role": "admin"},
        )

        assert response["code"] == 200
        assert [point["date"] for point in response["data"]["series"]] == [
            "2026-06-01",
            "2026-06-02",
            "2026-06-03",
        ]
        assert response["data"]["series"][0]["tokens_used"] == 30
        assert response["data"]["series"][1]["tokens_used"] == 0

    asyncio.run(run())


def test_dashboard_user_ranking_matches_frontend_contract(monkeypatch):
    async def run():
        from src.routes import dashboard

        class FakePool:
            async def fetch(self, query, *args):
                return [
                    {
                        "user_id": "00000000-0000-0000-0000-000000000001",
                        "username": "admin",
                        "email": "admin@example.com",
                        "conversations": 2,
                        "messages": 4,
                        "tokens_used": 300,
                        "files_uploaded": 3,
                        "avg_latency_ms": 125,
                        "last_active_at": None,
                    }
                ]

        async def fake_get_pool():
            return FakePool()

        monkeypatch.setattr(dashboard, "get_pool", fake_get_pool)

        response = await dashboard.user_stats(
            start_date=date(2026, 6, 1),
            end_date=date(2026, 6, 9),
            limit=10,
            sort_by="tokens_used",
            current_user={"role": "admin"},
        )

        assert response["code"] == 200
        assert response["data"]["users"][0]["username"] == "admin"
        assert response["data"]["users"][0]["tokens_used"] == 300

    asyncio.run(run())
