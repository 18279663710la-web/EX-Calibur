"""
Dify AI Platform SSE 代理服务

BFF 层: 接收前端对话请求, 转发至 Dify Workflow API, 流式透传响应。
不做任何数据校验、文件管理、向量去重、看板统计等业务逻辑。
"""

import json
import logging
from typing import AsyncGenerator

import httpx

from ..config import get_settings

logger = logging.getLogger(__name__)


def _sse_line(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


async def chat_stream(user_inputs: dict, username: str = "anonymous") -> AsyncGenerator[str, None]:
    """将用户输入转发至 Dify Workflow API，流式透传 SSE 事件。"""
    settings = get_settings()

    dify_url = f"{settings.dify_base_url}/workflows/run"
    dify_headers = {
        "Authorization": f"Bearer {settings.dify_api_key}",
        "Content-Type": "application/json",
    }
    dify_body = {
        "inputs": user_inputs,
        "response_mode": "streaming",
        "user": username,
    }
    dify_body_bytes = json.dumps(dify_body, ensure_ascii=False).encode("utf-8")

    try:
        async with httpx.AsyncClient(timeout=settings.dify_timeout_seconds) as client:
            async with client.stream(
                "POST", dify_url, headers=dify_headers, content=dify_body_bytes
            ) as response:
                if response.status_code != 200:
                    yield _sse_line("error", {
                        "code": 50201 if response.status_code >= 500 else 40001,
                        "message": f"AI 服务返回错误 (HTTP {response.status_code})",
                    })
                    return

                async for line in response.aiter_lines():
                    if not line or not line.startswith("data: "):
                        continue

                    data_str = line[6:]
                    if data_str == "[DONE]":
                        continue

                    try:
                        data = json.loads(data_str)
                    except json.JSONDecodeError:
                        continue

                    event_type = data.get("event", "")

                    if event_type == "text_chunk":
                        token_text = data.get("data", {}).get("text", "")
                        if token_text:
                            yield _sse_line("message", {"token": token_text})

                    elif event_type == "workflow_finished":
                        total_tokens = data.get("data", {}).get("total_tokens", 0)
                        yield _sse_line("done", {
                            "usage": {"total_tokens": total_tokens},
                        })

                    elif event_type == "error":
                        yield _sse_line("error", {
                            "code": 50001,
                            "message": data.get("message", "AI 服务内部错误"),
                        })
                        return

                    elif event_type in ("workflow_started", "node_started", "node_finished"):
                        pass

                    else:
                        yield f"data: {data_str}\n\n"

    except httpx.TimeoutException:
        yield _sse_line("error", {"code": 50401, "message": "AI 服务响应超时，请稍后重试"})
    except httpx.ConnectError:
        yield _sse_line("error", {"code": 50201, "message": "AI 服务不可用，请稍后重试"})
    except Exception as e:
        yield _sse_line("error", {"code": 50001, "message": f"后端处理异常: {str(e)}"})
