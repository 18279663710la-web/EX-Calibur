from datetime import datetime
from typing import Any
from pydantic import BaseModel, Field


class Meta(BaseModel):
    request_id: str = ""
    timestamp: str = ""
    latency_ms: int = 0


class Envelope(BaseModel):
    code: int
    message: str
    data: Any | None = None
    meta: Meta | None = None

    @classmethod
    def success(cls, data: Any = None, message: str = "success", code: int = 200) -> dict:
        return {
            "code": code,
            "message": message,
            "data": data,
            "meta": {
                "request_id": "",
                "timestamp": datetime.utcnow().isoformat() + "Z",
                "latency_ms": 0,
            },
        }

    @classmethod
    def error(cls, code: int, message: str, data: Any = None) -> dict:
        return {"code": code, "message": message, "data": data}


class PaginatedData(BaseModel):
    items: list[Any]
    total: int
    page: int
    page_size: int
    total_pages: int


class UserBrief(BaseModel):
    id: str
    username: str
    email: str
    avatar_url: str | None = None
    role: str = "user"


class FileInfo(BaseModel):
    id: str
    original_name: str
    mime_type: str
    size_bytes: int
    size_human: str
    tags: list[str] = []
    description: str | None = None
    processing_status: str = "pending"
    created_at: str


class ConversationBrief(BaseModel):
    id: str
    title: str | None = None
    model: str
    message_count: int = 0
    last_message_preview: str | None = None
    total_tokens: int = 0
    created_at: str
    updated_at: str


class MessageItem(BaseModel):
    id: str
    role: str
    content: str
    references: list[dict] | None = None
    usage: dict | None = None
    latency_ms: int | None = None
    created_at: str
