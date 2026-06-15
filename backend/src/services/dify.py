import json
import logging
import time
import uuid
from datetime import datetime, timezone
from typing import Any, AsyncGenerator

import httpx
from fastapi import UploadFile

from ..config import get_settings
from ..models.chat import (
    ChatRequest,
    SSEDoneEvent,
    SSEErrorEvent,
    SSEMessageToken,
    SSEMetaEvent,
    SSEReferencesEvent,
)

logger = logging.getLogger(__name__)


def _sse_line(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _dify_file_refs(file_ids: list[str]) -> list[dict[str, str]]:
    return [
        {
            "type": "document",
            "transfer_method": "local_file",
            "upload_file_id": file_id,
        }
        for file_id in file_ids
        if file_id
    ]


def build_dify_inputs(request: ChatRequest) -> dict[str, Any]:
    files = _dify_file_refs(request.file_ids)
    inputs: dict[str, Any] = {
        "query": request.query,
        "file_ids": ",".join(request.file_ids),
    }
    if files:
        inputs["files"] = files
    return inputs


def build_workflow_body(request: ChatRequest, *, user: str) -> dict[str, Any]:
    files = _dify_file_refs(request.file_ids)
    body: dict[str, Any] = {
        "inputs": build_dify_inputs(request),
        "response_mode": "streaming",
        "user": user,
    }
    if files:
        body["files"] = files
    return body


def build_chat_messages_body(request: ChatRequest, *, user: str) -> dict[str, Any]:
    files = _dify_file_refs(request.file_ids)
    body: dict[str, Any] = {
        "inputs": {
            "userinput": {
                "query": request.query,
                "files": files,
            }
        },
        "query": request.query,
        "response_mode": "streaming",
        "user": user,
    }
    if request.conversation_id:
        body["conversation_id"] = request.conversation_id
    if files:
        body["files"] = files
    return body


class DifyGateway:
    def __init__(
        self,
        *,
        base_url: str | None = None,
        api_key: str | None = None,
        timeout: int | None = None,
    ):
        settings = get_settings()
        self.base_url = (base_url or settings.dify_base_url).rstrip("/")
        self.api_key = api_key if api_key is not None else settings.dify_api_key
        self.timeout = timeout or settings.dify_timeout_seconds

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}"}

    async def upload_file(self, file: UploadFile, body: bytes, *, user: str) -> dict[str, Any]:
        url = f"{self.base_url}/files/upload"
        filename = file.filename or "upload.bin"
        mime_type = file.content_type or "application/octet-stream"
        files = {
            "file": (filename, body, mime_type),
            "user": (None, user),
        }

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(url, headers=self._headers(), files=files)

        if response.status_code >= 400:
            raise httpx.HTTPStatusError(
                f"Dify file upload failed with HTTP {response.status_code}",
                request=response.request,
                response=response,
            )
        return response.json()

    def stream_workflow(self, request: ChatRequest, *, user: str):
        url = f"{self.base_url}/workflows/run"
        headers = {
            **self._headers(),
            "Content-Type": "application/json",
        }
        body = build_workflow_body(request, user=user)
        content = json.dumps(body, ensure_ascii=False).encode("utf-8")
        return url, headers, content

    def stream_chat_messages(self, request: ChatRequest, *, user: str):
        url = f"{self.base_url}/chat-messages"
        headers = {
            **self._headers(),
            "Content-Type": "application/json",
        }
        body = build_chat_messages_body(request, user=user)
        content = json.dumps(body, ensure_ascii=False).encode("utf-8")
        return url, headers, content


def _extract_token(data: dict[str, Any]) -> str:
    event = data.get("event")
    payload = data.get("data") if isinstance(data.get("data"), dict) else {}
    if event == "text_chunk":
        return str(payload.get("text") or "")
    if event in {"agent_message", "message"}:
        return str(data.get("answer") or payload.get("answer") or "")
    return ""


class ThinkBlockFilter:
    def __init__(self):
        self._inside_think = False

    def push(self, text: str) -> str:
        output = []
        cursor = 0
        lowered = text.lower()

        while cursor < len(text):
            if self._inside_think:
                end = lowered.find("</think>", cursor)
                if end == -1:
                    return "".join(output)
                cursor = end + len("</think>")
                self._inside_think = False
                continue

            start = lowered.find("<think", cursor)
            if start == -1:
                output.append(text[cursor:])
                break

            output.append(text[cursor:start])
            close = lowered.find(">", start)
            if close == -1:
                self._inside_think = True
                break
            cursor = close + 1
            self._inside_think = True

        return "".join(output)


def _extract_usage(data: dict[str, Any]) -> dict[str, int]:
    payload = data.get("data") if isinstance(data.get("data"), dict) else {}
    metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
    usage = metadata.get("usage") if isinstance(metadata.get("usage"), dict) else {}
    total = payload.get("total_tokens") or usage.get("total_tokens") or 0
    prompt = usage.get("prompt_tokens") or 0
    completion = usage.get("completion_tokens") or 0
    return {
        "prompt_tokens": int(prompt or 0),
        "completion_tokens": int(completion or 0),
        "total_tokens": int(total or 0),
    }


def _is_not_workflow_app(payload: bytes) -> bool:
    try:
        data = json.loads(payload.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return False
    return data.get("code") == "not_workflow_app"


def _references_from_node(data: dict[str, Any]) -> list[dict[str, Any]]:
    payload = data.get("data") if isinstance(data.get("data"), dict) else {}
    if payload.get("node_type") != "knowledge-retrieval":
        return []
    outputs = payload.get("outputs") if isinstance(payload.get("outputs"), dict) else {}
    results = outputs.get("result")
    if not isinstance(results, list):
        return []

    chunks = []
    for index, chunk in enumerate(results):
        if not isinstance(chunk, dict):
            continue
        metadata = chunk.get("metadata") if isinstance(chunk.get("metadata"), dict) else {}
        chunks.append(
            {
                "index": index,
                "file_id": metadata.get("document_id", ""),
                "file_name": metadata.get("document_name", ""),
                "content": chunk.get("content") or chunk.get("text") or "",
                "score": float(chunk.get("score") or 0),
                "page_number": None,
            }
        )
    return chunks


async def chat_stream(
    user_id: str,
    username: str,
    request: ChatRequest,
) -> AsyncGenerator[str, None]:
    settings = get_settings()
    gateway = DifyGateway(
        base_url=settings.dify_base_url,
        api_key=settings.dify_api_key,
        timeout=settings.dify_timeout_seconds,
    )
    conversation_id = request.conversation_id or str(uuid.uuid4())
    dify_conversation_id = request.conversation_id
    message_id = f"msg_{uuid.uuid4()}"
    started = time.time()
    token_index = 0
    usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    think_filter = ThinkBlockFilter()

    yield _sse_line(
        "meta",
        SSEMetaEvent(
            conversation_id=conversation_id,
            model=request.model,
            created_at=datetime.now(timezone.utc).isoformat(),
            user_id=user_id,
        ).model_dump(),
    )
    yield _sse_line(
        "references",
        SSEReferencesEvent(chunks=[], total_retrieved=0).model_dump(),
    )

    try:
        async with httpx.AsyncClient(timeout=settings.dify_timeout_seconds) as client:
            attempts = [
                ("chat-messages", gateway.stream_chat_messages(request, user=username)),
            ]
            for mode, (url, headers, content) in attempts:
                logger.info(
                    "Forwarding chat to Dify %s: base_url=%s user=%s file_count=%s query_len=%s",
                    mode,
                    settings.dify_base_url,
                    username,
                    len(request.file_ids),
                    len(request.query),
                )
                async with client.stream("POST", url, headers=headers, content=content) as response:
                    logger.info("Dify %s response status=%s", mode, response.status_code)
                    if response.status_code != 200:
                        error_body = await response.aread()
                        if mode == "workflow" and response.status_code == 400 and _is_not_workflow_app(error_body):
                            logger.info("Dify API key is not a workflow app; falling back to chat-messages")
                            continue
                        yield _sse_line(
                            "error",
                            SSEErrorEvent(
                                code=50201 if response.status_code >= 500 else 40001,
                                message=f"Dify service returned HTTP {response.status_code}: {error_body.decode('utf-8', errors='replace')[:300]}",
                                conversation_id=conversation_id,
                            ).model_dump(),
                        )
                        return

                    async for line in response.aiter_lines():
                        if not line or not line.startswith("data: "):
                            continue
                        raw = line[6:]
                        if raw == "[DONE]":
                            continue
                        try:
                            data = json.loads(raw)
                        except json.JSONDecodeError:
                            logger.debug("Skipping malformed Dify SSE line: %s", raw)
                            continue

                        event_type = data.get("event", "")
                        if isinstance(data.get("conversation_id"), str) and data["conversation_id"]:
                            dify_conversation_id = data["conversation_id"]
                            conversation_id = dify_conversation_id
                        token = _extract_token(data)
                        if token:
                            token = think_filter.push(token)
                            if not token:
                                continue
                            yield _sse_line(
                                "message",
                                SSEMessageToken(token=token, index=token_index).model_dump(),
                            )
                            token_index += 1
                            continue

                        if event_type == "node_finished":
                            chunks = _references_from_node(data)
                            if chunks:
                                yield _sse_line(
                                    "references",
                                    SSEReferencesEvent(
                                        chunks=chunks,
                                        total_retrieved=len(chunks),
                                    ).model_dump(),
                                )
                            continue

                        if event_type in {"workflow_finished", "message_end"}:
                            event_data = data.get("data") if isinstance(data.get("data"), dict) else {}
                            status = event_data.get("status") or data.get("status")
                            error = event_data.get("error") or data.get("error")
                            if status == "failed" or error:
                                message = str(error or "Dify workflow failed")
                                yield _sse_line(
                                    "error",
                                    SSEErrorEvent(
                                        code=50202,
                                        message=f"Dify workflow failed: {message}",
                                        conversation_id=conversation_id,
                                    ).model_dump(),
                                )
                                return
                            usage = _extract_usage(data)
                            continue

                        if event_type == "error":
                            message = (
                                data.get("message")
                                or (data.get("data") or {}).get("message")
                                or "Dify service error"
                            )
                            yield _sse_line(
                                "error",
                                SSEErrorEvent(
                                    code=50001,
                                    message=str(message),
                                    conversation_id=conversation_id,
                                ).model_dump(),
                            )
                            return
                    break
            else:
                yield _sse_line(
                    "error",
                    SSEErrorEvent(
                        code=40001,
                        message="Dify app mode is not supported by this gateway",
                        conversation_id=conversation_id,
                    ).model_dump(),
                )
                return

    except httpx.TimeoutException:
        yield _sse_line(
            "error",
            SSEErrorEvent(
                code=50401,
                message="Dify service timed out",
                conversation_id=conversation_id,
            ).model_dump(),
        )
        return
    except httpx.ConnectError:
        yield _sse_line(
            "error",
            SSEErrorEvent(
                code=50201,
                message="Dify service is unavailable",
                conversation_id=conversation_id,
            ).model_dump(),
        )
        return
    except Exception as exc:
        logger.exception("Dify gateway stream failed: %s", exc)
        yield _sse_line(
            "error",
            SSEErrorEvent(
                code=50001,
                message=f"Gateway error: {exc}",
                conversation_id=conversation_id,
            ).model_dump(),
        )
        return

    latency_ms = int((time.time() - started) * 1000)
    logger.info(
        "Dify workflow stream finished: conversation_id=%s total_tokens=%s latency_ms=%s",
        conversation_id,
        usage.get("total_tokens", 0),
        latency_ms,
    )
    yield _sse_line(
        "done",
        SSEDoneEvent(
            conversation_id=dify_conversation_id or conversation_id,
            message_id=message_id,
            usage=usage,
            latency_ms=latency_ms,
            model=request.model,
            finished_at=datetime.now(timezone.utc).isoformat(),
        ).model_dump(),
    )


_dify_gateway: DifyGateway | None = None


def get_dify_gateway() -> DifyGateway:
    global _dify_gateway
    if _dify_gateway is None:
        _dify_gateway = DifyGateway()
    return _dify_gateway
