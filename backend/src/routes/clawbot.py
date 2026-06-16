from typing import Any

from fastapi import APIRouter, Depends

from ..models import Envelope
from ..services.channels import ChannelManager, get_channel_manager
from .channels import WeixinWebhookRequest, handle_weixin_event

router = APIRouter(prefix="/api/v1/clawbot", tags=["Clawbot"])


@router.get("/status")
async def clawbot_status():
    return {"status": "ok"}


async def get_manager() -> ChannelManager:
    return get_channel_manager()


@router.get("/weixin-state")
async def clawbot_weixin_state(manager: ChannelManager = Depends(get_manager)):
    channel = manager.get_channel("weixin")
    return _clawbot_success(
        {
            "status": "accepted",
            "channel": "weixin",
            "connected": bool(channel.connected) if channel else False,
            "running": bool(channel.running) if channel else False,
            "polling": bool(manager._weixin_poll_task and not manager._weixin_poll_task.done()),
            "cursor": manager._weixin_updates_cursor,
            "has_token": bool(getattr(manager.weixin_client, "token", "")),
        }
    )


@router.post("/webhook")
async def clawbot_webhook(
    payload: dict[str, Any],
    manager: ChannelManager = Depends(get_manager),
):
    return await _process_clawbot_payload(
        payload,
        manager=manager,
        protocol="clawbot_webhook",
    )


@router.post("/sendmessage")
async def clawbot_sendmessage(
    payload: dict[str, Any],
    manager: ChannelManager = Depends(get_manager),
):
    return await _process_clawbot_payload(
        payload,
        manager=manager,
        protocol="clawbot_sendmessage",
    )


@router.api_route("/getupdates", methods=["GET", "POST"])
async def clawbot_getupdates(
    payload: dict[str, Any] | None = None,
    manager: ChannelManager = Depends(get_manager),
):
    if not _payload_has_message(payload or {}):
        return _clawbot_success(
            {
                "status": "accepted",
                "channel": "weixin",
                "protocol": "clawbot_getupdates",
                "updates": [],
            }
        )
    return await _process_clawbot_payload(
        payload or {},
        manager=manager,
        protocol="clawbot_getupdates",
    )


@router.api_route("/sendtyping", methods=["GET", "POST"])
async def clawbot_sendtyping(payload: dict[str, Any] | None = None):
    return _clawbot_success(
        {
            "status": "accepted",
            "channel": "weixin",
            "protocol": "clawbot_sendtyping",
        }
    )


@router.api_route("/getconfig", methods=["GET", "POST"])
async def clawbot_getconfig(payload: dict[str, Any] | None = None):
    return _clawbot_success(
        {
            "status": "accepted",
            "channel": "weixin",
            "protocol": "clawbot_getconfig",
            "longpolling_timeout_ms": 25_000,
        }
    )


async def _process_clawbot_payload(
    payload: dict[str, Any],
    *,
    manager: ChannelManager,
    protocol: str,
):
    try:
        normalized = manager.normalize_clawbot_payload(payload)
    except ValueError as exc:
        return Envelope.error(40001, str(exc), data={"protocol": protocol})

    if manager.remember_message(normalized.get("message_id")):
        return _clawbot_success(
            {
                "status": "accepted",
                "channel": "weixin",
                "protocol": protocol,
                "duplicate": True,
                "message_id": normalized.get("message_id"),
            }
        )

    request = WeixinWebhookRequest(
        event_type=normalized["event_type"],
        user_id=normalized["user_id"],
        content=normalized.get("content") or "",
        file_name=normalized.get("file_name"),
        file_bytes_b64=normalized.get("file_bytes_b64"),
        context_token=normalized.get("context_token"),
        message_id=normalized.get("message_id"),
    )
    response = await handle_weixin_event(request, manager=manager)
    data = response.get("data")
    if isinstance(data, dict):
        data["protocol"] = protocol
    response["base_resp"] = {"ret": 0, "err_msg": "ok"}
    response["ret"] = 0
    response["errmsg"] = "ok"
    return response


def _clawbot_success(data: dict[str, Any]) -> dict[str, Any]:
    response = Envelope.success(data=data)
    response["base_resp"] = {"ret": 0, "err_msg": "ok"}
    response["ret"] = 0
    response["errmsg"] = "ok"
    return response


def _payload_has_message(payload: dict[str, Any]) -> bool:
    if not payload:
        return False
    if any(payload.get(key) for key in ("content", "text", "query", "item_list", "file_name")):
        return True
    msg = payload.get("msg")
    return isinstance(msg, dict) and _payload_has_message(msg)
