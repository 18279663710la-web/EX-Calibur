from fastapi import APIRouter, Depends, Query
from ..database import get_pool
from ..middleware.auth import get_current_user
from ..models import Envelope, FileInfo

router = APIRouter(prefix="/api/v1/files", tags=["Files"])


@router.get("")
async def list_files(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    folder: str = Query(""),
    current_user: dict = Depends(get_current_user),
):
    pool = await get_pool()
    offset = (page - 1) * page_size

    if folder:
        total = await pool.fetchval(
            "SELECT COUNT(*) FROM file_metadata WHERE uploaded_by = $1 AND deleted_at IS NULL AND folder = $2",
            current_user["sub"], folder,
        )
        rows = await pool.fetch(
            """SELECT id, original_name, mime_type, size_bytes, processing_status, created_at
               FROM file_metadata WHERE uploaded_by = $1 AND deleted_at IS NULL AND folder = $2
               ORDER BY created_at DESC LIMIT $3 OFFSET $4""",
            current_user["sub"], folder, page_size, offset,
        )
    else:
        total = await pool.fetchval(
            "SELECT COUNT(*) FROM file_metadata WHERE uploaded_by = $1 AND deleted_at IS NULL",
            current_user["sub"],
        )
        rows = await pool.fetch(
            """SELECT id, original_name, mime_type, size_bytes, processing_status, created_at
               FROM file_metadata WHERE uploaded_by = $1 AND deleted_at IS NULL
               ORDER BY created_at DESC LIMIT $2 OFFSET $3""",
            current_user["sub"], page_size, offset,
        )

    def _human(size: int) -> str:
        for unit in ("B", "KB", "MB", "GB"):
            if size < 1024:
                return f"{size:.1f} {unit}"
            size /= 1024
        return f"{size:.1f} TB"

    items = [
        {
            "id": str(r["id"]),
            "original_name": r["original_name"],
            "mime_type": r["mime_type"],
            "size_bytes": r["size_bytes"],
            "size_human": _human(r["size_bytes"]),
            "processing_status": r["processing_status"],
            "created_at": r["created_at"].isoformat() if r["created_at"] else "",
        }
        for r in rows
    ]

    return Envelope.success(data={
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": max(1, (total + page_size - 1) // page_size),
    })


@router.delete("/{file_id}")
async def delete_file(file_id: str, current_user: dict = Depends(get_current_user)):
    pool = await get_pool()
    row = await pool.fetchrow(
        "SELECT id, size_bytes FROM file_metadata WHERE id = $1 AND uploaded_by = $2 AND deleted_at IS NULL",
        file_id, current_user["sub"],
    )
    if not row:
        return Envelope.error(40401, "文件不存在")

    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE file_metadata SET deleted_at = NOW() WHERE id = $1", file_id,
        )
        await conn.execute(
            "UPDATE users SET quota_used_bytes = GREATEST(0, quota_used_bytes - $1) WHERE id = $2",
            row["size_bytes"], current_user["sub"],
        )

    return Envelope.success(data={"id": file_id, "deleted": True}, message="文件已删除")
