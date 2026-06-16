import base64
import json
import re
from typing import Any, Literal

import httpx
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from ..middleware.auth import get_current_user
from ..models import Envelope
from ..models.chat import ChatRequest
from ..services.channels import ChannelManager, extract_open_filename, get_channel_manager
from ..services.dify import chat_stream

router = APIRouter(prefix="/api/v1/channels", tags=["Channels"])


class ChannelActionRequest(BaseModel):
    channel: str = Field(..., min_length=1)
    action: Literal["connect", "disconnect"]
    config: dict[str, Any] | None = None


class QrLoginRequest(BaseModel):
    action: Literal["fetch", "poll", "refresh"] = "fetch"


class WeixinWebhookRequest(BaseModel):
    event_type: Literal["text", "file", "open_file"]
    user_id: str = Field(..., min_length=1)
    content: str = ""
    file_name: str | None = None
    file_bytes_b64: str | None = None
    context_token: str | None = None
    message_id: str | None = None


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


@router.post("/weixin/webhook")
async def weixin_webhook(
    body: WeixinWebhookRequest,
    manager: ChannelManager = Depends(get_manager),
):
    return await handle_weixin_event(body, manager=manager)


async def handle_weixin_event(
    body: WeixinWebhookRequest,
    *,
    manager: ChannelManager,
):
    selected_file = manager.resolve_file_choice(body.user_id, body.content)
    if body.event_type == "open_file" or selected_file:
        return await _deliver_weixin_file_request(body, manager=manager, selected_file=selected_file)

    if body.event_type == "text":
        matches = manager.find_knowledge_file_matches(body.content)
        if matches:
            return await _send_weixin_file_choices(body, manager=manager, matches=matches)

        dify_result = await _run_dify_text(body.user_id, body.content)
        answer = dify_result["answer"] or "已收到消息，但 Dify 未返回可发送内容。"
        delivery = await manager.send_weixin_text_reply(
            to_user=body.user_id,
            content=answer,
            context_token=body.context_token,
        )
        return Envelope.success(
            data={
                "status": "delivered",
                "channel": "weixin",
                "reply_type": "text",
                "message": {
                    "to_user": body.user_id,
                    "content": answer,
                },
                "delivery": delivery,
                "dify": dify_result,
            }
        )

    if body.event_type == "file":
        if not body.file_name or not body.file_bytes_b64:
            return Envelope.error(40001, "file_name and file_bytes_b64 are required")
        try:
            file_body = base64.b64decode(body.file_bytes_b64, validate=True)
        except ValueError:
            return Envelope.error(40001, "file_bytes_b64 is not valid base64")
        file_info = manager.store_weixin_file(file_name=body.file_name, body=file_body)
        delivery = await manager.send_weixin_text_reply(
            to_user=body.user_id,
            content=f"文件上传成功：{file_info['name']}",
            context_token=body.context_token,
        )
        return Envelope.success(
            data={
                "status": "delivered",
                "channel": "weixin",
                "reply_type": "file_received",
                "file": file_info,
                "delivery": delivery,
            }
        )

    return await _deliver_weixin_file_request(body, manager=manager)


async def _deliver_weixin_file_request(
    body: WeixinWebhookRequest,
    *,
    manager: ChannelManager,
    selected_file: str | None = None,
):
    filename = selected_file or body.file_name or _extract_open_filename(body.content)
    if not filename:
        matches = manager.find_knowledge_file_matches(body.content)
        if matches:
            return await _send_weixin_file_choices(body, manager=manager, matches=matches)
        return Envelope.error(40001, "file_name or open-file content is required")

    if not selected_file:
        candidate_matches = manager.find_knowledge_file_matches(filename)
        if len(candidate_matches) > 1:
            return await _send_weixin_file_choices(body, manager=manager, matches=candidate_matches)
        if len(candidate_matches) == 1:
            filename = candidate_matches[0]["file_name"]

    manager.clear_file_choices(body.user_id)
    try:
        send_file = manager.build_send_file_payload(to_user=body.user_id, filename=filename)
    except FileNotFoundError:
        matches = manager.find_knowledge_file_matches(filename)
        if matches:
            return await _send_weixin_file_choices(body, manager=manager, matches=matches)
        return Envelope.error(40401, "文件不存在")
    delivery = await manager.send_weixin_file_reply(
        to_user=body.user_id,
        file_name=send_file["file_name"],
        path=send_file["path"],
        context_token=body.context_token,
    )
    return Envelope.success(
        data={
            "status": "delivered",
            "channel": "weixin",
            "reply_type": "send_file",
            "message": send_file,
            "delivery": delivery,
        }
    )


async def _send_weixin_file_choices(
    body: WeixinWebhookRequest,
    *,
    manager: ChannelManager,
    matches: list[dict[str, Any]],
):
    manager.remember_file_choices(body.user_id, [item["file_name"] for item in matches])
    content = _format_file_choices(body.content, matches)
    delivery = await manager.send_weixin_text_reply(
        to_user=body.user_id,
        content=content,
        context_token=body.context_token,
    )
    return Envelope.success(
        data={
            "status": "delivered",
            "channel": "weixin",
            "reply_type": "open_file_choices",
            "message": {
                "to_user": body.user_id,
                "content": content,
            },
            "choices": matches,
            "delivery": delivery,
        }
    )


def _extract_open_filename(content: str) -> str:
    text = extract_open_filename(content)
    text = re.sub(r"^(打开|查看|预览|发送|回传)\s*", "", text)
    return text.strip()


def _looks_like_open_file_request(content: str) -> bool:
    return False


def _format_file_choices(content: str, matches: list[dict[str, Any]]) -> str:
    lines = [
        f"根据搜索关键词 “{content}”，找到以下 {len(matches)} 个匹配文件（按匹配度从高到低排序）：",
        "",
    ]
    for index, item in enumerate(matches, start=1):
        score = item.get("score")
        if isinstance(score, (int, float)):
            score_text = f"{score:.0f}%"
        else:
            score_text = str(score or "未知")
        lines.append(f"{index}. {item.get('file_name')}（匹配度：{score_text}）")
    lines.extend(["", "请问您想打开哪一个？请回复序号（如“1”）或完整文件名。"])
    return "\n".join(lines)


async def _legacy_weixin_webhook(
    body: WeixinWebhookRequest,
    manager: ChannelManager,
):
    if body.event_type == "text":
        dify_result = await _run_dify_text(body.user_id, body.content)
        return Envelope.success(
            data={
                "status": "delivered",
                "channel": "weixin",
                "reply_type": "text",
                "message": {
                    "to_user": body.user_id,
                    "content": dify_result["answer"],
                },
                "dify": dify_result,
            }
        )

    if body.event_type == "file":
        if not body.file_name or not body.file_bytes_b64:
            return Envelope.error(40001, "file_name and file_bytes_b64 are required")
        try:
            file_body = base64.b64decode(body.file_bytes_b64, validate=True)
        except ValueError:
            return Envelope.error(40001, "file_bytes_b64 is not valid base64")
        file_info = manager.store_weixin_file(file_name=body.file_name, body=file_body)
        return Envelope.success(
            data={
                "status": "stored",
                "channel": "weixin",
                "reply_type": "file_received",
                "file": file_info,
            }
        )

    filename = body.file_name or extract_open_filename(body.content)
    if not filename:
        return Envelope.error(40001, "file_name or open-file content is required")
    try:
        send_file = manager.build_send_file_payload(to_user=body.user_id, filename=filename)
    except FileNotFoundError:
        return Envelope.error(40401, "文件不存在")
    return Envelope.success(
        data={
            "status": "delivered",
            "channel": "weixin",
            "reply_type": "send_file",
            "message": send_file,
        }
    )


@router.get("/health")
async def channels_health():
    return {"status": "ok"}


async def _run_dify_text(user_id: str, query: str) -> dict[str, Any]:
    events = [chunk async for chunk in chat_stream(
        user_id=user_id,
        username=user_id,
        request=ChatRequest(query=query),
    )]
    answer_parts: list[str] = []
    references: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    for event, data in _parse_sse_events(events):
        if event == "message":
            answer_parts.append(str(data.get("token") or ""))
        elif event == "references" and data.get("chunks"):
            references = data["chunks"]
        elif event == "error":
            errors.append(data)
    return {
        "status": "error" if errors else "ok",
        "answer": "".join(answer_parts),
        "references": references,
        "errors": errors,
    }


def _parse_sse_events(events: list[str]) -> list[tuple[str, dict[str, Any]]]:
    parsed: list[tuple[str, dict[str, Any]]] = []
    for block in re.split(r"\r?\n\r?\n", "".join(events).strip()):
        if not block:
            continue
        event = "message"
        data_lines: list[str] = []
        for line in block.splitlines():
            if line.startswith("event:"):
                event = line.split(":", 1)[1].strip()
            elif line.startswith("data:"):
                data_lines.append(line.split(":", 1)[1].strip())
        if data_lines:
            parsed.append((event, json.loads("\n".join(data_lines))))
    return parsed
