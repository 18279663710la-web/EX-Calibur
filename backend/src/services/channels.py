import base64
import io
import json
import os
import random
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote

import httpx
import qrcode

from ..config import get_settings


DEFAULT_BASE_URL = "https://ilinkai.weixin.qq.com"
CDN_BASE_URL = "https://novac2c.cdn.weixin.qq.com/c2c"
DEFAULT_API_TIMEOUT = 15
QR_POLL_TIMEOUT = 35
BOT_TYPE = "3"
CHANNEL_VERSION = "2.0.0"
CLIENT_VERSION = "131072"
QR_MAX_REFRESHES = 10


@dataclass
class ChannelState:
    name: str
    label: str
    label_i18n: dict[str, str]
    icon: str
    color: str
    description: str
    active: bool = True
    running: bool = False
    connected: bool = False
    status: str = "offline"
    login_status: str = "not_connected"
    fields: list[dict[str, Any]] = field(default_factory=list)
    qrcode: str | None = None
    qr_login_url: str | None = None
    qr_image: str | None = None
    qr_status: str = "idle"
    bot_id: str | None = None
    qr_refresh_count: int = 0
    updated_at: str | None = None

    def public_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "label": self.label,
            "label_i18n": self.label_i18n,
            "icon": self.icon,
            "color": self.color,
            "running": self.running,
            "connected": self.connected,
            "active": self.active,
            "status": self.status,
            "login_status": self.login_status,
            "fields": self.fields,
            "description": self.description,
        }


class ILinkWeixinClient:
    def __init__(
        self,
        *,
        base_url: str = DEFAULT_BASE_URL,
        cdn_base_url: str = CDN_BASE_URL,
        token: str = "",
        timeout: float = DEFAULT_API_TIMEOUT,
    ):
        self.base_url = base_url or DEFAULT_BASE_URL
        self.cdn_base_url = cdn_base_url or CDN_BASE_URL
        self.token = token
        self.timeout = timeout

    async def fetch_qr_code(self) -> dict[str, Any]:
        url = _ensure_trailing_slash(self.base_url) + f"ilink/bot/get_bot_qrcode?bot_type={BOT_TYPE}"
        async with httpx.AsyncClient(timeout=DEFAULT_API_TIMEOUT) as client:
            response = await client.get(url)
        response.raise_for_status()
        return response.json()

    async def poll_qr_status(self, qrcode: str, timeout: int = QR_POLL_TIMEOUT) -> dict[str, Any]:
        url = (
            _ensure_trailing_slash(self.base_url)
            + f"ilink/bot/get_qrcode_status?qrcode={quote(qrcode)}"
        )
        headers = {
            "iLink-App-Id": "bot",
            "iLink-App-ClientVersion": CLIENT_VERSION,
        }
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.get(url, headers=headers)
            response.raise_for_status()
            return response.json()
        except httpx.ReadTimeout:
            return {"status": "wait"}

    async def get_bot_qrcode(self, bot_type: int = 3) -> dict[str, Any]:
        return await self.fetch_qr_code()

    async def get_qrcode_status(self, qrcode: str) -> dict[str, Any]:
        return await self.poll_qr_status(qrcode)


class ChannelManager:
    def __init__(
        self,
        *,
        weixin_client: ILinkWeixinClient | None = None,
        credentials_path: str | None = None,
    ):
        settings = get_settings()
        self._started = False
        self.weixin_client = weixin_client or ILinkWeixinClient(
            base_url=settings.weixin_base_url or DEFAULT_BASE_URL,
            cdn_base_url=settings.weixin_cdn_base_url or CDN_BASE_URL,
            token=settings.weixin_token,
        )
        self.credentials_path = credentials_path or settings.weixin_credentials_path
        self._channels: dict[str, ChannelState] = {
            "weixin": ChannelState(
                name="weixin",
                label="WeChat",
                label_i18n={"zh": "微信", "en": "WeChat"},
                icon="message-circle",
                color="#07C160",
                description="WeChat iLink bot QR login channel",
            ),
            "webhook": ChannelState(
                name="webhook",
                label="Webhook",
                label_i18n={"zh": "Webhook", "en": "Webhook"},
                icon="webhook",
                color="#111827",
                description="Generic HTTP callback channel",
                fields=[
                    {"name": "url", "label": "Callback URL", "type": "url", "required": True}
                ],
            ),
        }
        self._load_weixin_credentials()

    async def startup(self):
        self._started = True
        self._load_weixin_credentials()

    async def shutdown(self):
        self._started = False
        for channel in self._channels.values():
            channel.running = False

    def list_channels(self) -> list[dict[str, Any]]:
        return [channel.public_dict() for channel in self._channels.values()]

    def get_channel(self, name: str) -> ChannelState | None:
        return self._channels.get(name)

    async def connect(self, name: str, config: dict[str, Any] | None = None) -> dict[str, Any]:
        channel = self._require_channel(name)
        if name == "weixin":
            return await self.create_qr_login(action="fetch")

        channel.running = True
        channel.connected = True
        channel.status = "connected"
        channel.login_status = "connected"
        channel.updated_at = _now()
        return {"status": "connected", "message": f"{name} channel connected"}

    async def disconnect(self, name: str) -> dict[str, Any]:
        channel = self._require_channel(name)
        channel.running = False
        channel.connected = False
        channel.status = "offline"
        channel.login_status = "not_connected"
        channel.qrcode = None
        channel.qr_login_url = None
        channel.qr_image = None
        channel.qr_status = "idle"
        channel.bot_id = None
        channel.qr_refresh_count = 0
        channel.updated_at = _now()
        if name == "weixin":
            self._clear_weixin_credentials()
        return {"status": "disconnected", "message": f"{name} channel disconnected"}

    async def create_qr_login(self, action: str = "fetch") -> dict[str, Any]:
        channel = self._require_channel("weixin")

        if action in {"fetch", "refresh"} or not channel.qrcode:
            await self._fetch_weixin_qrcode(channel, reset_refresh_count=True)

        if action == "poll":
            return await self._poll_weixin_qrcode(channel)

        return self._qr_result(channel)

    async def _fetch_weixin_qrcode(
        self,
        channel: ChannelState,
        *,
        reset_refresh_count: bool = False,
    ):
        fetch = getattr(self.weixin_client, "fetch_qr_code", None)
        if fetch is None:
            fetch = getattr(self.weixin_client, "get_bot_qrcode")
            payload = await fetch(bot_type=3)
        else:
            payload = await fetch()

        qrcode = _extract_required(payload, ("qrcode",))
        qrcode_content = _first_str(payload, ("qrcode_img_content",)) or qrcode
        channel.qrcode = qrcode
        channel.qr_login_url = qrcode_content
        channel.qr_image = _qr_data_uri(qrcode_content)
        channel.qr_status = "pending"
        channel.connected = False
        channel.running = True
        channel.status = "waiting_qr"
        channel.login_status = "pending"
        if reset_refresh_count:
            channel.qr_refresh_count = 0
        channel.updated_at = _now()

    async def _poll_weixin_qrcode(self, channel: ChannelState) -> dict[str, Any]:
        if not channel.qrcode:
            return await self.create_qr_login(action="fetch")

        poll = getattr(self.weixin_client, "poll_qr_status", None)
        if poll is None:
            poll = getattr(self.weixin_client, "get_qrcode_status")
        try:
            payload = await poll(channel.qrcode)
        except httpx.ReadTimeout:
            payload = {"status": "wait"}

        status = _normalize_qr_status(payload)
        channel.qr_status = status
        channel.login_status = status
        channel.updated_at = _now()

        if status == "confirmed":
            bot_token = _first_str(payload, ("bot_token", "token", "access_token"))
            bot_id = _first_str(payload, ("ilink_bot_id", "bot_id"))
            if not bot_token or not bot_id:
                raise ValueError("Login confirmed but missing token/bot_id")
            result_base_url = _first_str(payload, ("baseurl", "base_url")) or self.weixin_client.base_url
            channel.running = False
            channel.connected = True
            channel.status = "connected"
            channel.bot_id = bot_id
            if hasattr(self.weixin_client, "token"):
                self.weixin_client.token = bot_token
            if hasattr(self.weixin_client, "base_url"):
                self.weixin_client.base_url = result_base_url
            self._save_weixin_credentials(payload, bot_token, result_base_url, bot_id)
        elif status == "expired":
            channel.qr_refresh_count += 1
            if channel.qr_refresh_count >= QR_MAX_REFRESHES:
                channel.running = False
                channel.connected = False
                channel.status = "expired"
            else:
                await self._fetch_weixin_qrcode(channel)
        else:
            channel.running = True
            channel.connected = False
            channel.status = "waiting_qr"

        return self._qr_result(channel)

    def _qr_result(self, channel: ChannelState) -> dict[str, Any]:
        return {
            "status": "connected" if channel.connected else "pending",
            "message": "Scan the QR code with WeChat to connect this channel",
            "qrcode_url": channel.qr_login_url,
            "qr_image": channel.qr_image,
            "qr_status": channel.qr_status,
            "bot_id": channel.bot_id or "weixin",
        }

    def _load_weixin_credentials(self):
        channel = self._channels.get("weixin")
        if not channel or not self.credentials_path or not os.path.exists(self.credentials_path):
            return
        try:
            with open(self.credentials_path, "r", encoding="utf-8") as handle:
                credentials = json.load(handle)
        except (OSError, json.JSONDecodeError):
            return

        bot_token = _first_str(credentials, ("token", "bot_token"))
        if not bot_token:
            return
        base_url = _first_str(credentials, ("base_url", "baseurl"))
        if hasattr(self.weixin_client, "token"):
            self.weixin_client.token = bot_token
        if base_url and hasattr(self.weixin_client, "base_url"):
            self.weixin_client.base_url = base_url
        channel.connected = True
        channel.running = False
        channel.status = "connected"
        channel.login_status = "confirmed"
        channel.bot_id = _first_str(credentials, ("bot_id", "ilink_bot_id", "uin", "wxid", "robot_id"))
        channel.updated_at = credentials.get("saved_at") or _now()

    def _save_weixin_credentials(
        self,
        payload: dict[str, Any],
        token: str,
        base_url: str,
        bot_id: str,
    ):
        if not self.credentials_path:
            return
        os.makedirs(os.path.dirname(self.credentials_path) or ".", exist_ok=True)
        credentials = {
            "saved_at": _now(),
            "token": token,
            "base_url": base_url,
            "bot_id": bot_id,
            "user_id": _first_str(payload, ("ilink_user_id", "user_id")) or "",
            "raw": payload,
        }
        with open(self.credentials_path, "w", encoding="utf-8") as handle:
            json.dump(credentials, handle, ensure_ascii=False, indent=2)

    def _clear_weixin_credentials(self):
        if self.credentials_path and os.path.exists(self.credentials_path):
            os.remove(self.credentials_path)

    def _require_channel(self, name: str) -> ChannelState:
        channel = self.get_channel(name)
        if not channel:
            raise KeyError(name)
        return channel


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _random_wechat_uin() -> str:
    value = random.randint(0, 0xFFFFFFFF)
    return base64.b64encode(str(value).encode("utf-8")).decode("utf-8")


def _build_headers(token: str = "") -> dict[str, str]:
    headers = {
        "Content-Type": "application/json",
        "AuthorizationType": "ilink_bot_token",
        "X-WECHAT-UIN": _random_wechat_uin(),
        "iLink-App-Id": "bot",
        "iLink-App-ClientVersion": CLIENT_VERSION,
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _ensure_trailing_slash(url: str) -> str:
    return url if url.endswith("/") else url + "/"


def _extract_required(payload: dict[str, Any], keys: tuple[str, ...]) -> str:
    value = _first_str(payload, keys)
    if not value:
        raise ValueError(f"Missing QR code in iLink response: {payload}")
    return value


def _first_str(payload: dict[str, Any], keys: tuple[str, ...]) -> str | None:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, str) and value:
            return value
    data = payload.get("data")
    if isinstance(data, dict):
        for key in keys:
            value = data.get(key)
            if isinstance(value, str) and value:
                return value
    return None


def _normalize_qr_status(payload: dict[str, Any]) -> str:
    raw = _first_str(payload, ("status", "qr_status", "state")) or str(payload.get("code", ""))
    normalized = raw.lower()
    if normalized in {"confirmed", "success", "scanned_confirmed", "ok", "0", "200"}:
        return "confirmed"
    if normalized in {"scaned", "scanned"}:
        return "scaned"
    if normalized == "wait":
        return "pending"
    if normalized in {"expired", "timeout", "cancelled", "canceled", "408"}:
        return "expired"
    return "pending"


def _qr_data_uri(value: str) -> str:
    image = qrcode.make(value)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    return f"data:image/png;base64,{encoded}"


_channel_manager: ChannelManager | None = None


def get_channel_manager() -> ChannelManager:
    global _channel_manager
    if _channel_manager is None:
        _channel_manager = ChannelManager()
    return _channel_manager
