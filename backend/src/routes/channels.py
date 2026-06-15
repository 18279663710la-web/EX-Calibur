from typing import Any, Literal

import httpx
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from ..middleware.auth import get_current_user
from ..models import Envelope
from ..services.channels import ChannelManager, get_channel_manager

router = APIRouter(prefix="/api/v1/channels", tags=["Channels"])


class ChannelActionRequest(BaseModel):
    channel: str = Field(..., min_length=1)
    action: Literal["connect", "disconnect"]
    config: dict[str, Any] | None = None


class QrLoginRequest(BaseModel):
    action: Literal["fetch", "poll", "refresh"] = "fetch"


async def get_manager() -> ChannelManager:
    return get_channel_manager()


@router.get("")
async def list_channels(
    current_user: dict = Depends(get_current_user),
    manager: ChannelManager = Depends(get_manager),
):
    return Envelope.success(data={"channels": manager.list_channels()})


@router.post("")
async def change_channel_state(
    body: ChannelActionRequest,
    current_user: dict = Depends(get_current_user),
    manager: ChannelManager = Depends(get_manager),
):
    try:
        if body.action == "connect":
            data = await manager.connect(body.channel, body.config)
        else:
            data = await manager.disconnect(body.channel)
    except KeyError:
        return Envelope.error(40401, f"Channel not found: {body.channel}")
    except (httpx.HTTPError, ValueError) as exc:
        return Envelope.error(50201, f"WeChat ClawBot service error: {exc}")

    return Envelope.success(data=data)


@router.post("/weixin/qrlogin")
async def qr_login(
    body: QrLoginRequest,
    current_user: dict = Depends(get_current_user),
    manager: ChannelManager = Depends(get_manager),
):
    try:
        data = await manager.create_qr_login(body.action)
    except (httpx.HTTPError, ValueError) as exc:
        return Envelope.error(50201, f"WeChat ClawBot service error: {exc}")
    return Envelope.success(data=data)


@router.get("/health")
async def channels_health():
    return {"status": "ok"}
