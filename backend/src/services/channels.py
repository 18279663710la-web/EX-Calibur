import asyncio
import base64
import hashlib
import io
import json
import logging
import os
import random
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx
import qrcode

from ..config import get_settings
from .file_matcher import resolve_best_match, search_knowledge_files
from .file_matcher import normalize_query, resolve_best_match, search_knowledge_files


DEFAULT_BASE_URL = "https://ilinkai.weixin.qq.com"
CDN_BASE_URL = "https://novac2c.cdn.weixin.qq.com/c2c"
DEFAULT_API_TIMEOUT = 15
QR_POLL_TIMEOUT = 35
BOT_TYPE = "3"
CHANNEL_VERSION = "2.0.0"
CLIENT_VERSION = "131072"
QR_MAX_REFRESHES = 10
MAX_RECENT_WEIXIN_MESSAGES = 1024
UPLOAD_MAX_RETRIES = 3
OPEN_FILE_INTENTS = (
    "打开",
    "查看",
    "预览",
    "发送",
    "回传",
    "给我",
    "发我",
    "传给我",
    "完整",
    "文档",
    "文件",
)

logger = logging.getLogger(__name__)


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

    async def get_updates(self, get_updates_buf: str = "", timeout: int = 35) -> dict[str, Any]:
        return await self._post_json(
            "ilink/bot/getupdates",
            {
                "get_updates_buf": get_updates_buf,
            },
            timeout=timeout + 5,
        )

    async def get_upload_url(
        self,
        *,
        filekey: str,
        media_type: int,
        to_user_id: str,
        rawsize: int,
        rawfilemd5: str,
        filesize: int,
        aeskey: str,
    ) -> dict[str, Any]:
        return await self._post_json(
            "ilink/bot/getuploadurl",
            {
                "filekey": filekey,
                "media_type": media_type,
                "to_user_id": to_user_id,
                "rawsize": rawsize,
                "rawfilemd5": rawfilemd5,
                "filesize": filesize,
                "aeskey": aeskey,
                "no_need_thumb": True,
            },
        )

    async def send_text(
        self,
        *,
        to_user: str,
        content: str,
        context_token: str | None = None,
    ) -> dict[str, Any]:
        client_id = uuid.uuid4().hex
        payload = await self._post_json(
            "ilink/bot/sendmessage",
            {
                "msg": {
                    "from_user_id": "",
                    "to_user_id": to_user,
                    "client_id": client_id[:16],
                    "message_type": 2,
                    "message_state": 2,
                    "context_token": context_token or "",
                    "item_list": [
                        {
                            "type": 1,
                            "text_item": {"text": content},
                        }
                    ],
                },
                "base_info": {},
            },
        )
        return {
            "message_id": _first_str(payload, ("message_id", "msg_id")) or client_id,
            "transport": "weixin_api",
            "send_status": "delivered",
            "raw": payload,
        }

    async def send_file(
        self,
        *,
        to_user: str,
        file_name: str,
        path: str | None = None,
        content: bytes | None = None,
        context_token: str | None = None,
    ) -> dict[str, Any]:
        client_id = uuid.uuid4().hex[:16]
        if content is not None and path is None:
            tmp_dir = Path(os.getenv("TMPDIR", os.getenv("TEMP", "/tmp")))
            tmp_dir.mkdir(parents=True, exist_ok=True)
            temp_file = tmp_dir / f"wx_upload_{client_id}_{Path(file_name).name}"
            temp_file.write_bytes(content)
            path = str(temp_file)
        if not path:
            raise ValueError("path or content is required for send_file")
        upload_result = await asyncio.to_thread(
            upload_media_to_cdn,
            self,
            path,
            to_user,
            3,
        )
        payload = await self.send_file_item(
            to=to_user,
            context_token=context_token or "",
            encrypt_query_param=upload_result["encrypt_query_param"],
            aes_key_b64=upload_result["aes_key_b64"],
            file_name=file_name or Path(path).name,
            file_size=upload_result["raw_size"],
        )
        return {
            "message_id": _first_str(payload, ("message_id", "msg_id")) or client_id,
            "transport": "weixin_api",
            "send_status": "delivered",
            "raw": payload,
        }

    async def send_file_item(
        self,
        *,
        to: str,
        context_token: str,
        encrypt_query_param: str,
        aes_key_b64: str,
        file_name: str,
        file_size: int,
        text: str = "",
    ) -> dict[str, Any]:
        items: list[dict[str, Any]] = []
        if text:
            items.append({"type": 1, "text_item": {"text": text}})
        items.append(
            {
                "type": 4,
                "file_item": {
                    "media": {
                        "encrypt_query_param": encrypt_query_param,
                        "aes_key": aes_key_b64,
                        "encrypt_type": 1,
                    },
                    "file_name": file_name,
                    "len": str(file_size),
                },
            }
        )
        return await self._send_items(to, context_token, items)

    async def send_typing(self, user_id: str, typing_ticket: str, status: int = 1) -> dict[str, Any]:
        return await self._post_json(
            "ilink/bot/sendtyping",
            {
                "ilink_user_id": user_id,
                "typing_ticket": typing_ticket,
                "status": status,
            },
            timeout=10,
        )

    async def get_config(self, user_id: str, context_token: str = "") -> dict[str, Any]:
        return await self._post_json(
            "ilink/bot/getconfig",
            {
                "ilink_user_id": user_id,
                "context_token": context_token,
            },
            timeout=10,
        )

    async def _send_items(self, to: str, context_token: str, items: list[dict[str, Any]]) -> dict[str, Any]:
        return await self._post_json(
            "ilink/bot/sendmessage",
            {
                "msg": {
                    "from_user_id": "",
                    "to_user_id": to,
                    "client_id": uuid.uuid4().hex[:16],
                    "message_type": 2,
                    "message_state": 2,
                    "item_list": items,
                    "context_token": context_token,
                },
            },
        )

    async def _post_json(self, path: str, body: dict[str, Any], timeout: int | None = None) -> dict[str, Any]:
        url = _ensure_trailing_slash(self.base_url) + path
        body.setdefault("base_info", {}).setdefault("channel_version", CHANNEL_VERSION)
        async with httpx.AsyncClient(timeout=timeout or self.timeout) as client:
            response = await client.post(url, headers=_build_headers(self.token), json=body)
        response.raise_for_status()
        if not response.content:
            return {}
        try:
            return response.json()
        except json.JSONDecodeError:
            return {"raw_text": response.text}


class ChannelManager:
    def __init__(
        self,
        *,
        weixin_client: ILinkWeixinClient | None = None,
        credentials_path: str | None = None,
        knowledge_dir: str | Path | None = None,
    ):
        settings = get_settings()
        self._started = False
        self.weixin_client = weixin_client or ILinkWeixinClient(
            base_url=settings.weixin_base_url or DEFAULT_BASE_URL,
            cdn_base_url=settings.weixin_cdn_base_url or CDN_BASE_URL,
            token=settings.weixin_token,
        )
        self.credentials_path = credentials_path or settings.weixin_credentials_path
        self.knowledge_dir = Path(knowledge_dir or os.getenv("AGENT_KNOWLEDGE_DIR", "knowledge")).resolve()
        self._seen_message_ids: dict[str, str] = {}
        self._weixin_context_tokens: dict[str, str] = {}
        self._weixin_file_choices: dict[str, list[str]] = {}
        self._weixin_updates_cursor = ""
        self._weixin_poll_task: asyncio.Task | None = None
        self._weixin_stop_event = asyncio.Event()
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
        channel = self._channels.get("weixin")
        if channel and channel.connected:
            self.start_weixin_polling()

    async def shutdown(self):
        self._started = False
        await self.stop_weixin_polling()
        for channel in self._channels.values():
            channel.running = False

    def list_channels(self) -> list[dict[str, Any]]:
        return [channel.public_dict() for channel in self._channels.values()]

    def get_channel(self, name: str) -> ChannelState | None:
        return self._channels.get(name)

    async def connect(self, name: str, config: dict[str, Any] | None = None) -> dict[str, Any]:
        channel = self._require_channel(name)
        if name == "weixin":
            if channel.connected:
                self.start_weixin_polling()
                result = self._qr_result(channel)
                result["status"] = "connected"
                result["polling"] = self._weixin_poll_task is not None and not self._weixin_poll_task.done()
                return result
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
            await self.stop_weixin_polling()
            self._clear_weixin_credentials()
        return {"status": "disconnected", "message": f"{name} channel disconnected"}

    async def create_qr_login(self, action: str = "fetch") -> dict[str, Any]:
        channel = self._require_channel("weixin")

        if action in {"fetch", "refresh"} or not channel.qrcode:
            await self._fetch_weixin_qrcode(channel, reset_refresh_count=True)

        if action == "poll":
            return await self._poll_weixin_qrcode(channel)

        return self._qr_result(channel)

    def store_weixin_file(
        self,
        *,
        file_name: str,
        body: bytes,
    ) -> dict[str, Any]:
        safe_name = Path(str(file_name or "upload.bin").replace("\\", "/")).name
        if not safe_name:
            safe_name = "upload.bin"
        self.knowledge_dir.mkdir(parents=True, exist_ok=True)
        target = self.knowledge_dir / safe_name
        target.write_bytes(body)
        return {
            "name": safe_name,
            "path": str(target),
            "size_bytes": target.stat().st_size,
            "extension": target.suffix,
        }

    def start_weixin_polling(self) -> bool:
        channel = self._channels.get("weixin")
        if not channel or not channel.connected:
            return False
        if not getattr(self.weixin_client, "token", ""):
            return False
        if self._weixin_poll_task and not self._weixin_poll_task.done():
            return True
        self._weixin_stop_event = asyncio.Event()
        self._weixin_poll_task = asyncio.create_task(self._weixin_poll_loop())
        channel.running = True
        channel.status = "connected"
        logger.info("weixin polling started")
        return True

    async def stop_weixin_polling(self):
        self._weixin_stop_event.set()
        task = self._weixin_poll_task
        self._weixin_poll_task = None
        if task and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        logger.info("weixin polling stopped")

    async def poll_weixin_once(self) -> dict[str, Any]:
        get_updates = getattr(self.weixin_client, "get_updates", None)
        if get_updates is None:
            raise ValueError("WeChat client does not support get_updates")
        payload = await get_updates(self._weixin_updates_cursor)
        ret = int(payload.get("ret") or payload.get("errcode") or 0)
        if ret != 0:
            return {
                "status": "error",
                "ret": ret,
                "errmsg": payload.get("errmsg") or payload.get("message") or "",
                "processed": 0,
                "cursor": self._weixin_updates_cursor,
            }
        cursor = payload.get("get_updates_buf")
        if isinstance(cursor, str) and cursor:
            self._weixin_updates_cursor = cursor
        processed = 0
        for raw_msg in payload.get("msgs") or []:
            if await self.process_weixin_update(raw_msg):
                processed += 1
        return {
            "status": "ok",
            "processed": processed,
            "cursor": self._weixin_updates_cursor,
        }

    async def process_weixin_update(self, raw_msg: dict[str, Any]) -> bool:
        if int(raw_msg.get("message_type") or 0) != 1:
            return False
        message_id = _first_str_nested(raw_msg, ("message_id", "msg_id", "msgid", "seq", "id"))
        if self.remember_message(message_id):
            return False
        normalized = self.normalize_clawbot_payload(raw_msg)
        if normalized["event_type"] == "file" and not normalized.get("file_bytes_b64"):
            downloaded_path = await self._download_weixin_file_item(raw_msg, normalized.get("file_name"))
            if downloaded_path:
                normalized["file_bytes_b64"] = base64.b64encode(Path(downloaded_path).read_bytes()).decode("ascii")
        context_token = normalized.get("context_token")
        user_id = normalized["user_id"]
        if context_token:
            self._weixin_context_tokens[user_id] = context_token
        if not normalized.get("context_token"):
            normalized["context_token"] = self._weixin_context_tokens.get(user_id)

        from ..routes.channels import WeixinWebhookRequest, handle_weixin_event

        request = WeixinWebhookRequest(
            event_type=normalized["event_type"],
            user_id=user_id,
            content=normalized.get("content") or "",
            file_name=normalized.get("file_name"),
            file_bytes_b64=normalized.get("file_bytes_b64"),
            context_token=normalized.get("context_token"),
            message_id=normalized.get("message_id"),
        )
        response = await handle_weixin_event(request, manager=self)
        if response.get("code") != 200:
            logger.error("weixin update failed message_id=%s response=%s", message_id, response)
        return True

    async def _download_weixin_file_item(self, raw_msg: dict[str, Any], file_name: str | None) -> str | None:
        item = _first_message_item(raw_msg)
        file_item = item.get("file_item") if isinstance(item.get("file_item"), dict) else {}
        media = file_item.get("media") if isinstance(file_item.get("media"), dict) else {}
        encrypt_query_param = _first_str(media, ("encrypt_query_param",))
        aes_key = _first_str(media, ("aes_key",)) or _first_str(file_item, ("aeskey",))
        if not encrypt_query_param or not aes_key:
            return None
        safe_name = Path(str(file_name or file_item.get("file_name") or uuid.uuid4().hex)).name
        tmp_dir = Path(os.getenv("TMPDIR", os.getenv("TEMP", "/tmp")))
        tmp_dir.mkdir(parents=True, exist_ok=True)
        save_path = tmp_dir / f"wx_inbound_{uuid.uuid4().hex[:8]}_{safe_name}"
        return await asyncio.to_thread(
            download_media_from_cdn,
            getattr(self.weixin_client, "cdn_base_url", CDN_BASE_URL),
            encrypt_query_param,
            aes_key,
            str(save_path),
        )

    async def _weixin_poll_loop(self):
        failures = 0
        while not self._weixin_stop_event.is_set():
            try:
                await self.poll_weixin_once()
                failures = 0
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                failures += 1
                logger.error("weixin polling failed count=%s error=%s", failures, exc, exc_info=True)
            delay = 2 if failures < 3 else 30
            try:
                await asyncio.wait_for(self._weixin_stop_event.wait(), timeout=delay)
            except asyncio.TimeoutError:
                pass

    def build_send_file_payload(self, *, to_user: str, filename: str) -> dict[str, Any]:
        target = self.resolve_knowledge_file(filename)
        if target is None:
            raise FileNotFoundError(filename)
        return {
            "to_user": to_user,
            "file_name": target.name,
            "path": str(target),
            "size_bytes": target.stat().st_size,
            "transfer_method": "local_file_path",
        }

    def resolve_knowledge_file(self, filename: str) -> Path | None:
        return resolve_best_match(filename, knowledge_dir=self.knowledge_dir)

    async def send_weixin_text_reply(
        self,
        *,
        to_user: str,
        content: str,
        context_token: str | None = None,
    ) -> dict[str, Any]:
        if self._should_simulate_delivery(context_token):
            return self._simulated_delivery(to_user=to_user)
        send_text = getattr(self.weixin_client, "send_text", None)
        if send_text is None:
            raise ValueError("WeChat client does not support send_text")
        return _normalize_delivery_result(
            await send_text(to_user=to_user, content=content, context_token=context_token),
            to_user=to_user,
        )

    async def send_weixin_file_reply(
        self,
        *,
        to_user: str,
        file_name: str,
        path: str | None = None,
        content: bytes | None = None,
        context_token: str | None = None,
    ) -> dict[str, Any]:
        if self._should_simulate_delivery(context_token):
            return self._simulated_delivery(to_user=to_user)
        send_file = getattr(self.weixin_client, "send_file", None)
        if send_file is None:
            raise ValueError("WeChat client does not support send_file")
        return _normalize_delivery_result(
            await send_file(
                to_user=to_user,
                file_name=file_name,
                path=path,
                content=content,
                context_token=context_token,
            ),
            to_user=to_user,
        )

    def remember_message(self, message_id: str | None) -> bool:
        value = str(message_id or "").strip()
        if not value:
            return False
        if value in self._seen_message_ids:
            return True
        self._seen_message_ids[value] = _now()
        while len(self._seen_message_ids) > MAX_RECENT_WEIXIN_MESSAGES:
            self._seen_message_ids.pop(next(iter(self._seen_message_ids)))
        return False

    def normalize_clawbot_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        item = _first_message_item(payload)
        item_type = item.get("type")
        file_item = item.get("file_item") if isinstance(item.get("file_item"), dict) else {}
        content = _first_str_nested(payload, ("content", "text", "query")) or _text_from_item(item)
        file_name = (
            _first_str_nested(payload, ("file_name", "filename", "name"))
            or _first_str(file_item, ("file_name", "filename", "name"))
        )
        file_bytes_b64 = _first_str_nested(payload, ("file_bytes_b64", "file_base64", "base64"))
        if not file_bytes_b64 and isinstance(file_item.get("content_b64"), str):
            file_bytes_b64 = file_item["content_b64"]
        if not file_bytes_b64:
            file_path = _first_str_nested(payload, ("file_path", "local_path", "path"))
            if file_path and Path(file_path).is_file():
                file_bytes_b64 = base64.b64encode(Path(file_path).read_bytes()).decode("ascii")

        user_id = _first_str_nested(
            payload,
            (
                "from_user_id",
                "from_user",
                "from_wxid",
                "talker",
                "sender",
                "sender_id",
                "user_id",
            ),
        )
        if not user_id:
            raise ValueError("ClawBot payload missing from_user_id")

        if file_name and (file_bytes_b64 or item_type == 4):
            event_type = "file"
        elif file_name or self.resolve_file_choice(user_id, content) or _looks_like_open_file(content):
            event_type = "open_file"
        else:
            event_type = "text"

        normalized = {
            "event_type": event_type,
            "user_id": user_id,
            "content": content or "",
            "file_name": file_name,
            "file_bytes_b64": file_bytes_b64,
            "context_token": _first_str_nested(payload, ("context_token", "contextToken")),
            "message_id": _first_str_nested(
                payload,
                ("message_id", "msg_id", "msgid", "client_id", "id"),
            ),
        }
        logger.info(
            "weixin inbound normalized event_type=%s user_id=%s message_id=%s",
            normalized["event_type"],
            normalized["user_id"],
            normalized["message_id"],
        )
        return normalized

    def _should_simulate_delivery(self, context_token: str | None) -> bool:
        return isinstance(self.weixin_client, ILinkWeixinClient) and not self.weixin_client.token

    def _simulated_delivery(self, *, to_user: str) -> dict[str, Any]:
        return {
            "to_user": to_user,
            "message_id": f"simulated-{uuid.uuid4().hex[:12]}",
            "transport": "simulation",
            "send_status": "simulated",
        }

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
            setattr(self.weixin_client, "token", bot_token)
            setattr(self.weixin_client, "base_url", result_base_url)
            self._save_weixin_credentials(payload, bot_token, result_base_url, bot_id)
            self.start_weixin_polling()
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
        setattr(self.weixin_client, "token", bot_token)
        if base_url:
            setattr(self.weixin_client, "base_url", base_url)
        channel.connected = True
        channel.running = self._weixin_poll_task is not None and not self._weixin_poll_task.done()
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

    def remember_file_choices(self, user_id: str, filenames: list[str]):
        cleaned = [Path(str(name or "")).name for name in filenames if str(name or "").strip()]
        if cleaned:
            self._weixin_file_choices[user_id] = cleaned[:10]
        else:
            self.clear_file_choices(user_id)

    def clear_file_choices(self, user_id: str):
        self._weixin_file_choices.pop(user_id, None)

    def resolve_file_choice(self, user_id: str, content: str) -> str | None:
        text = str(content or "").strip()
        if not text.isdigit():
            return None
        index = int(text)
        if index < 1:
            return None
        choices = self._weixin_file_choices.get(user_id) or []
        if index > len(choices):
            return None
        return choices[index - 1]

    def find_knowledge_file_matches(self, query: str, *, limit: int = 5) -> list[dict[str, Any]]:
        return search_knowledge_files(query, knowledge_dir=self.knowledge_dir, top_k=limit)


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


def _first_str_nested(payload: dict[str, Any], keys: tuple[str, ...]) -> str | None:
    value = _first_str(payload, keys)
    if value:
        return value
    for nested_key in ("msg", "message", "payload"):
        nested = payload.get(nested_key)
        if isinstance(nested, dict):
            value = _first_str_nested(nested, keys)
            if value:
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


def _aes_ecb_encrypt(data: bytes, key: bytes) -> bytes:
    from Crypto.Cipher import AES

    pad_len = 16 - (len(data) % 16)
    padded = data + bytes([pad_len] * pad_len)
    cipher = AES.new(key, AES.MODE_ECB)
    return cipher.encrypt(padded)


def _aes_ecb_decrypt(data: bytes, key: bytes) -> bytes:
    from Crypto.Cipher import AES

    cipher = AES.new(key, AES.MODE_ECB)
    decrypted = cipher.decrypt(data)
    pad_len = decrypted[-1]
    if pad_len > 16:
        return decrypted
    return decrypted[:-pad_len]


def _md5_bytes(data: bytes) -> str:
    return hashlib.md5(data).hexdigest()


def _aes_ecb_padded_size(plaintext_size: int) -> int:
    return ((plaintext_size + 1 + 15) // 16) * 16


async def _run_sync_awaitable(value: Any) -> Any:
    if hasattr(value, "__await__"):
        return await value
    return value


def upload_media_to_cdn(api: ILinkWeixinClient, file_path: str, to_user_id: str, media_type: int) -> dict[str, Any]:
    aes_key = os.urandom(16)
    aes_key_hex = aes_key.hex()
    filekey = uuid.uuid4().hex
    raw_data = Path(file_path).read_bytes()
    raw_size = len(raw_data)
    raw_md5 = _md5_bytes(raw_data)
    cipher_size = _aes_ecb_padded_size(raw_size)
    encrypted = _aes_ecb_encrypt(raw_data, aes_key)

    async def _upload_once() -> dict[str, Any]:
        last_error: Exception | None = None
        for attempt in range(1, UPLOAD_MAX_RETRIES + 1):
            current_filekey = filekey if attempt == 1 else uuid.uuid4().hex
            try:
                upload_meta = await api.get_upload_url(
                    filekey=current_filekey,
                    media_type=media_type,
                    to_user_id=to_user_id,
                    rawsize=raw_size,
                    rawfilemd5=raw_md5,
                    filesize=cipher_size,
                    aeskey=aes_key_hex,
                )
                upload_full_url = upload_meta.get("upload_full_url", "")
                upload_param = upload_meta.get("upload_param", "")
                if upload_full_url:
                    cdn_url = upload_full_url
                elif upload_param:
                    cdn_url = (
                        f"{api.cdn_base_url}/upload"
                        f"?encrypted_query_param={quote(upload_param)}"
                        f"&filekey={quote(current_filekey)}"
                    )
                else:
                    raise RuntimeError(f"getUploadUrl missing upload URL: {upload_meta}")
                async with httpx.AsyncClient(timeout=120) as client:
                    response = await client.post(
                        cdn_url,
                        content=encrypted,
                        headers={
                            "Content-Type": "application/octet-stream",
                            "Content-Length": str(len(encrypted)),
                        },
                    )
                if 400 <= response.status_code < 500:
                    raise RuntimeError(
                        f"CDN client error {response.status_code}: "
                        f"{response.headers.get('x-error-message', response.text[:200])}"
                    )
                response.raise_for_status()
                download_param = response.headers.get("x-encrypted-param", "")
                if not download_param:
                    raise RuntimeError("CDN response missing x-encrypted-param header")
                return {
                    "encrypt_query_param": download_param,
                    "aes_key_b64": base64.b64encode(aes_key_hex.encode("utf-8")).decode("utf-8"),
                    "ciphertext_size": cipher_size,
                    "raw_size": raw_size,
                }
            except Exception as exc:
                last_error = exc
                if attempt >= UPLOAD_MAX_RETRIES or "CDN client error" in str(exc):
                    break
        raise last_error or RuntimeError("CDN upload failed")

    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(_upload_once())
    finally:
        loop.close()


def download_media_from_cdn(
    cdn_base_url: str,
    encrypt_query_param: str,
    aes_key: str,
    save_path: str,
) -> str:
    url = f"{cdn_base_url}/download?encrypted_query_param={quote(encrypt_query_param)}"
    response = httpx.get(url, timeout=60)
    response.raise_for_status()

    try:
        key_bytes = bytes.fromhex(aes_key)
        if len(key_bytes) != 16:
            raise ValueError()
    except (ValueError, TypeError):
        decoded = base64.b64decode(aes_key)
        if len(decoded) == 32:
            key_bytes = bytes.fromhex(decoded.decode("ascii"))
        elif len(decoded) == 16:
            key_bytes = decoded
        else:
            raise ValueError(f"Invalid AES key length after base64 decode: {len(decoded)}")

    decrypted = _aes_ecb_decrypt(response.content, key_bytes)
    target = Path(save_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(decrypted)
    return str(target)


def extract_open_filename(content: str) -> str:
    return normalize_query(content)


def _normalize_delivery_result(result: Any, *, to_user: str) -> dict[str, Any]:
    payload = result if isinstance(result, dict) else {}
    return {
        "to_user": to_user,
        "message_id": _first_str(payload, ("message_id", "msg_id")) or f"wx-{uuid.uuid4().hex[:12]}",
        "transport": _first_str(payload, ("transport",)) or "weixin_api",
        "send_status": _first_str(payload, ("send_status", "status")) or "delivered",
    }


def _first_message_item(payload: dict[str, Any]) -> dict[str, Any]:
    item_list = payload.get("item_list") or payload.get("items") or []
    if isinstance(item_list, list):
        for item in item_list:
            if isinstance(item, dict):
                return item
    msg = payload.get("msg")
    if isinstance(msg, dict):
        return _first_message_item(msg)
    return {}


def _text_from_item(item: dict[str, Any]) -> str:
    text_item = item.get("text_item")
    if isinstance(text_item, dict):
        return _first_str(text_item, ("text", "string")) or ""
    return ""


def _looks_like_open_file(content: str) -> bool:
    text = str(content or "").strip()
    if not text:
        return False
    lowered = text.lower()
    return any(token in text for token in OPEN_FILE_INTENTS) or any(
        token in lowered for token in ("open", "view", "preview", "send", "file", "document")
    )


def _normalize_file_query(content: str) -> str:
    text = str(content or "").strip()
    if not text:
        return ""
    for prefix in ("打开", "查看", "预览", "发送", "回传"):
        if text.startswith(prefix):
            text = text[len(prefix):].strip()
            break
    for token in (
        "请",
        "帮我",
        "把",
        "完整的",
        "完整",
        "文档",
        "文件",
        "给我",
        "发我",
        "传给我",
        "打开",
        "查看",
        "预览",
        "发送",
        "回传",
        "一下",
        "这个",
        "那个",
    ):
        text = text.replace(token, " ")
    punctuation_chars = "\"'`,.:;!?()[]{}<>"
    for ch in punctuation_chars:
        text = text.replace(ch, ' ')
    text = ' '.join(text.split())
    return text


def _file_match_score(query: str, file_name: str) -> float:
    normalized_query = _compact_for_match(_normalize_file_query(query))
    normalized_name = _compact_for_match(file_name)
    normalized_stem = _compact_for_match(Path(file_name).stem)
    if not normalized_query:
        return 0
    if normalized_query == normalized_name or normalized_query == normalized_stem:
        return 100
    if normalized_name.startswith(normalized_query) or normalized_stem.startswith(normalized_query):
        return 95
    if normalized_query in normalized_name or normalized_query in normalized_stem:
        return 90
    query_parts = [part for part in re.split(r"[^0-9a-zA-Z一-鿿]+", normalized_query) if part]
    if not query_parts:
        return 0
    hits = sum(1 for part in query_parts if part in normalized_name or part in normalized_stem)
    if hits:
        return max(50, hits / len(query_parts) * 80)
    return 0


def _compact_for_match(value: str) -> str:
    return ''.join(ch for ch in str(value or '').lower() if ch.isdigit() or ('a' <= ch <= 'z') or ('一' <= ch <= '鿿'))


_channel_manager: ChannelManager | None = None


def get_channel_manager() -> ChannelManager:
    global _channel_manager
    if _channel_manager is None:
        _channel_manager = ChannelManager()
    return _channel_manager
