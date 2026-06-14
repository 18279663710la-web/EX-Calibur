from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from ..models.chat import ChatRequest
from ..services.dify import chat_stream

router = APIRouter(prefix="/api/v1/knowledge-base", tags=["Knowledge Base"])


@router.post("/chat")
async def chat(body: ChatRequest):
    inputs = {"query": body.query}
    return StreamingResponse(
        chat_stream(inputs, username="anonymous"),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
