import httpx
from fastapi import APIRouter, BackgroundTasks, Depends, File, Query, UploadFile
from fastapi.responses import StreamingResponse

from ..database import get_pool
from ..middleware.auth import get_current_user
from ..models import Envelope
from ..models.chat import ChatRequest
from ..services import dynamic_rag
from ..services.dify import chat_stream, get_dify_gateway

router = APIRouter(prefix="/api/v1/knowledge-base", tags=["Knowledge Base"])

dify_gateway = get_dify_gateway()


@router.post("/chat/upload", status_code=201)
async def upload_chat_files(
    files: list[UploadFile] = File(...),
    background_tasks: BackgroundTasks = None,
    current_user: dict = Depends(get_current_user),
):
    if not files:
        return Envelope.error(42201, "Please choose files to upload")
    if len(files) > dynamic_rag.MAX_CHAT_UPLOAD_FILES:
        return Envelope.error(42202, "A maximum of 5 files can be uploaded at once")

    items = []
    for file in files:
        if not dynamic_rag.is_allowed_chat_upload(file.filename):
            return Envelope.error(42203, "File type is not allowed")

        body = await file.read()
        if len(body) > dynamic_rag.MAX_CHAT_UPLOAD_BYTES:
            return Envelope.error(41301, "Single file size must not exceed 15 MB")

        try:
            payload = await dify_gateway.upload_file(
                file,
                body,
                user=current_user.get("username") or current_user["sub"],
            )
        except httpx.HTTPError as exc:
            return Envelope.error(50201, f"Dify file upload failed: {exc}")

        dify_file_id = str(payload.get("id") or payload.get("upload_file_id") or "")
        if not dify_file_id:
            return Envelope.error(50201, "Dify file upload response missing file id")

        size_bytes = int(payload.get("size") or len(body))
        items.append(
            {
                "id": dify_file_id,
                "original_name": payload.get("name") or file.filename,
                "mime_type": payload.get("mime_type") or file.content_type or "application/octet-stream",
                "size_bytes": size_bytes,
                "size_human": _size_human(size_bytes),
                "processing_status": "ready",
                "dedup_status": "not_applicable",
                "rag_mode": "forwarded",
            }
        )

    return Envelope.success(
        data={
            "items": items,
            "file_ids": [item["id"] for item in items],
            "status_message": None,
        },
        message="File forwarded to Dify",
        code=201,
    )


@router.post("/chat")
async def chat(
    body: ChatRequest,
    current_user: dict = Depends(get_current_user),
):
    return StreamingResponse(
        chat_stream(
            user_id=current_user["sub"],
            username=current_user.get("username", "unknown"),
            request=body,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/conversations")
async def list_conversations(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    current_user: dict = Depends(get_current_user),
):
    pool = await get_pool()
    offset = (page - 1) * page_size

    total = await pool.fetchval(
        "SELECT COUNT(*) FROM conversations WHERE user_id = $1",
        current_user["sub"],
    )

    rows = await pool.fetch(
        """
        SELECT
            c.id, c.title, c.model, c.created_at, c.updated_at,
            COUNT(m.id) AS message_count,
            COALESCE(SUM(m.total_tokens), 0) AS total_tokens,
            (SELECT m2.content FROM messages m2
             WHERE m2.conversation_id = c.id AND m2.role = 'assistant'
             ORDER BY m2.created_at DESC LIMIT 1
            ) AS last_message_preview
        FROM conversations c
        LEFT JOIN messages m ON m.conversation_id = c.id
        WHERE c.user_id = $1
        GROUP BY c.id
        ORDER BY c.updated_at DESC
        LIMIT $2 OFFSET $3
        """,
        current_user["sub"],
        page_size,
        offset,
    )

    items = [
        {
            "id": str(r["id"]),
            "title": r["title"],
            "model": r["model"],
            "message_count": r["message_count"],
            "last_message_preview": (r["last_message_preview"] or "")[:100]
            if r["last_message_preview"]
            else None,
            "total_tokens": r["total_tokens"],
            "created_at": r["created_at"].isoformat() if r["created_at"] else "",
            "updated_at": r["updated_at"].isoformat() if r["updated_at"] else "",
        }
        for r in rows
    ]

    return Envelope.success(
        data={
            "items": items,
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": max(1, (total + page_size - 1) // page_size),
        }
    )


@router.get("/conversations/{conversation_id}")
async def get_conversation(
    conversation_id: str,
    current_user: dict = Depends(get_current_user),
):
    pool = await get_pool()

    conv = await pool.fetchrow(
        """SELECT id, title, model, created_at, updated_at
           FROM conversations WHERE id = $1 AND user_id = $2""",
        conversation_id,
        current_user["sub"],
    )

    if not conv:
        return Envelope.error(40401, "Conversation not found")

    msg_rows = await pool.fetch(
        """SELECT id, role, content, prompt_tokens, completion_tokens,
                  total_tokens, latency_ms, references_json, created_at
           FROM messages
           WHERE conversation_id = $1
           ORDER BY created_at""",
        conversation_id,
    )

    messages = []
    for m in msg_rows:
        msg_obj = {
            "id": str(m["id"]),
            "role": m["role"],
            "content": m["content"],
            "references": m["references_json"] if m["references_json"] else None,
            "created_at": m["created_at"].isoformat() if m["created_at"] else "",
        }
        if m["role"] == "assistant":
            msg_obj["usage"] = {
                "prompt_tokens": m["prompt_tokens"],
                "completion_tokens": m["completion_tokens"],
                "total_tokens": m["total_tokens"],
            }
            msg_obj["latency_ms"] = m["latency_ms"]
        messages.append(msg_obj)

    return Envelope.success(
        data={
            "id": str(conv["id"]),
            "title": conv["title"],
            "model": conv["model"],
            "messages": messages,
            "created_at": conv["created_at"].isoformat() if conv["created_at"] else "",
            "updated_at": conv["updated_at"].isoformat() if conv["updated_at"] else "",
        }
    )


@router.delete("/conversations/{conversation_id}")
async def delete_conversation(
    conversation_id: str,
    current_user: dict = Depends(get_current_user),
):
    pool = await get_pool()

    conv = await pool.fetchrow(
        "SELECT id FROM conversations WHERE id = $1 AND user_id = $2",
        conversation_id,
        current_user["sub"],
    )
    if not conv:
        return Envelope.error(40401, "Conversation not found")

    await pool.execute("DELETE FROM messages WHERE conversation_id = $1", conversation_id)
    await pool.execute(
        "DELETE FROM conversations WHERE id = $1 AND user_id = $2",
        conversation_id,
        current_user["sub"],
    )

    return Envelope.success(
        data={"id": conversation_id, "deleted": True},
        message="Conversation deleted",
    )


def _size_human(size: int) -> str:
    if size < 1024:
        return f"{size} B"
    if size < 1024 * 1024:
        return f"{size / 1024:.2f} KB"
    return f"{size / 1024 / 1024:.2f} MB"
