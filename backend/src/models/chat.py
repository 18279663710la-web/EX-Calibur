from pydantic import BaseModel, Field, field_validator
from typing import Any


class RetrievalConfig(BaseModel):
    top_k: int = 5
    score_threshold: float = 0.7
    rerank_enabled: bool = True


class ChatRequest(BaseModel):
    conversation_id: str | None = None
    query: str = Field(..., min_length=1, max_length=4000)
    file_ids: list[str] = []
    model: str = "gpt-4o"
    retrieval_config: RetrievalConfig | None = None
    system_prompt_override: str | None = None
    system_notes: list[str] = []


class SSEMetaEvent(BaseModel):
    conversation_id: str
    model: str
    created_at: str
    user_id: str


class SSEReferenceChunk(BaseModel):
    index: int
    file_id: str
    file_name: str
    content: str
    score: float
    page_number: int | None = None


class SSEReferencesEvent(BaseModel):
    chunks: list[SSEReferenceChunk]
    total_retrieved: int


class SSEMessageToken(BaseModel):
    token: str
    index: int


class SSEToolCallEvent(BaseModel):
    tool_name: str
    status: str
    input: dict | None = None
    output: str | None = None
    duration_ms: int | None = None
    timestamp: str


class SSEErrorEvent(BaseModel):
    code: int
    message: str
    conversation_id: str | None = None


class SSEDoneEvent(BaseModel):
    conversation_id: str
    message_id: str
    usage: dict
    latency_ms: int
    model: str
    finished_at: str
