from datetime import date, timedelta
from typing import Any, Literal

from fastapi import APIRouter, Depends, Query

from ..database import get_pool
from ..middleware.auth import get_current_user
from ..models import Envelope

router = APIRouter(prefix="/api/v1/dashboard", tags=["Dashboard"])


def _require_admin(current_user: dict) -> dict | None:
    if current_user.get("role") != "admin":
        return Envelope.error(40301, "Dashboard data is only available to administrators")
    return None


def _date_bounds(start_date: date, end_date: date) -> tuple[date, date]:
    if end_date < start_date:
        start_date, end_date = end_date, start_date
    return start_date, end_date + timedelta(days=1)


def _int(value: Any) -> int:
    return int(value or 0)


def _float(value: Any) -> float:
    return float(value or 0)


def _human_bytes(value: int) -> str:
    units = ["B", "KB", "MB", "GB", "TB"]
    amount = float(value)
    for unit in units:
        if amount < 1024 or unit == units[-1]:
            return f"{amount:.2f} {unit}" if unit != "B" else f"{int(amount)} B"
        amount /= 1024
    return f"{amount:.2f} TB"


def _human_tokens(value: int) -> str:
    if value >= 1_000_000:
        return f"{value / 1_000_000:.2f}M"
    if value >= 1_000:
        return f"{value / 1_000:.2f}K"
    return str(value)


def _row_value(row: Any, key: str, default: Any = 0) -> Any:
    if row is None:
        return default
    try:
        value = row[key]
    except (KeyError, TypeError):
        value = getattr(row, key, default)
    return default if value is None else value


@router.get("/overview")
async def overview(current_user: dict = Depends(get_current_user)):
    denied = _require_admin(current_user)
    if denied:
        return denied

    pool = await get_pool()
    row = await pool.fetchrow("SELECT COUNT(*) AS count FROM conversations")
    conv_count = _int(_row_value(row, "count"))

    return Envelope.success(
        data={
            "conversations": conv_count,
            "files": 0,
            "active_users": 1,
            "total_tokens": 0,
        }
    )


@router.get("/stats")
async def stats(
    start_date: date = Query(...),
    end_date: date = Query(...),
    current_user: dict = Depends(get_current_user),
):
    denied = _require_admin(current_user)
    if denied:
        return denied

    start, end_exclusive = _date_bounds(start_date, end_date)
    pool = await get_pool()

    conversation_row = await pool.fetchrow(
        """
        SELECT
            COUNT(*) AS total_conversations,
            COALESCE(AVG(conversation_tokens.total_tokens), 0)::INTEGER AS avg_tokens_per_conversation
        FROM conversations c
        LEFT JOIN (
            SELECT conversation_id, SUM(total_tokens) AS total_tokens
            FROM messages
            GROUP BY conversation_id
        ) conversation_tokens ON conversation_tokens.conversation_id = c.id
        WHERE c.created_at >= $1 AND c.created_at < $2
        """,
        start,
        end_exclusive,
    )
    message_row = await pool.fetchrow(
        """
        SELECT
            COUNT(*) AS total_messages,
            COALESCE(SUM(prompt_tokens), 0) AS input_tokens,
            COALESCE(SUM(completion_tokens), 0) AS output_tokens,
            COALESCE(SUM(total_tokens), 0) AS total_tokens,
            COALESCE(AVG(latency_ms), 0)::INTEGER AS avg_latency_ms,
            COALESCE(percentile_cont(0.50) WITHIN GROUP (ORDER BY latency_ms), 0)::INTEGER AS p50_latency_ms,
            COALESCE(percentile_cont(0.95) WITHIN GROUP (ORDER BY latency_ms), 0)::INTEGER AS p95_latency_ms,
            COALESCE(percentile_cont(0.99) WITHIN GROUP (ORDER BY latency_ms), 0)::INTEGER AS p99_latency_ms,
            COALESCE(MAX(latency_ms), 0) AS max_latency_ms,
            COALESCE(MIN(latency_ms), 0) AS min_latency_ms
        FROM messages m
        WHERE m.created_at >= $1 AND m.created_at < $2
        """,
        start,
        end_exclusive,
    )
    file_row = await pool.fetchrow(
        """
        SELECT
            COUNT(*) AS total_files_uploaded,
            COALESCE(SUM(size_bytes), 0) AS total_storage_bytes
        FROM file_metadata
        WHERE deleted_at IS NULL AND created_at >= $1 AND created_at < $2
        """,
        start,
        end_exclusive,
    )
    active_user_row = await pool.fetchrow(
        """
        SELECT COUNT(DISTINCT user_id) AS active_users
        FROM operation_logs
        WHERE user_id IS NOT NULL AND created_at >= $1 AND created_at < $2
        """,
        start,
        end_exclusive,
    )
    model_rows = await pool.fetch(
        """
        SELECT
            c.model AS model,
            COUNT(*) FILTER (WHERE m.role = 'assistant') AS call_count,
            COALESCE(SUM(m.total_tokens), 0) AS total_tokens,
            COALESCE(AVG(m.latency_ms), 0)::INTEGER AS avg_latency_ms
        FROM conversations c
        JOIN messages m ON m.conversation_id = c.id
        WHERE m.created_at >= $1 AND m.created_at < $2
        GROUP BY c.model
        ORDER BY call_count DESC, total_tokens DESC
        """,
        start,
        end_exclusive,
    )

    total_conversations = _int(_row_value(conversation_row, "total_conversations"))
    total_tokens = _int(_row_value(message_row, "total_tokens"))
    input_tokens = _int(_row_value(message_row, "input_tokens"))
    output_tokens = _int(_row_value(message_row, "output_tokens"))
    total_storage = _int(_row_value(file_row, "total_storage_bytes"))

    return Envelope.success(
        data={
            "summary": {
                "total_conversations": total_conversations,
                "total_messages": _int(_row_value(message_row, "total_messages")),
                "total_files_uploaded": _int(_row_value(file_row, "total_files_uploaded")),
                "total_storage_bytes": total_storage,
                "total_storage_human": _human_bytes(total_storage),
                "active_users": _int(_row_value(active_user_row, "active_users")),
            },
            "token_consumption": {
                "total_tokens": total_tokens,
                "total_tokens_human": _human_tokens(total_tokens),
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "avg_tokens_per_conversation": _int(
                    _row_value(conversation_row, "avg_tokens_per_conversation")
                ),
                "estimated_cost_usd": round((input_tokens * 0.0000005) + (output_tokens * 0.0000015), 4),
            },
            "latency": {
                "avg_latency_ms": _int(_row_value(message_row, "avg_latency_ms")),
                "p50_latency_ms": _int(_row_value(message_row, "p50_latency_ms")),
                "p95_latency_ms": _int(_row_value(message_row, "p95_latency_ms")),
                "p99_latency_ms": _int(_row_value(message_row, "p99_latency_ms")),
                "max_latency_ms": _int(_row_value(message_row, "max_latency_ms")),
                "min_latency_ms": _int(_row_value(message_row, "min_latency_ms")),
            },
            "model_breakdown": [
                {
                    "model": row["model"] or "unknown",
                    "call_count": _int(row["call_count"]),
                    "total_tokens": _int(row["total_tokens"]),
                    "avg_latency_ms": _int(row["avg_latency_ms"]),
                }
                for row in model_rows
            ],
            "period": {"start_date": start_date.isoformat(), "end_date": end_date.isoformat()},
        }
    )


@router.get("/stats/timeline")
async def timeline(
    start_date: date = Query(...),
    end_date: date = Query(...),
    granularity: Literal["daily"] = "daily",
    current_user: dict = Depends(get_current_user),
):
    denied = _require_admin(current_user)
    if denied:
        return denied

    start, end_exclusive = _date_bounds(start_date, end_date)
    pool = await get_pool()
    rows = await pool.fetch(
        """
        SELECT
            day::date AS date,
            COUNT(DISTINCT c.id) AS conversations,
            COUNT(DISTINCT m.id) AS messages,
            COALESCE(SUM(m.total_tokens), 0) AS tokens_used,
            COALESCE(AVG(m.latency_ms), 0)::INTEGER AS avg_latency_ms,
            COUNT(DISTINCT f.id) AS files_uploaded,
            COUNT(DISTINCT l.user_id) AS active_users,
            COUNT(DISTINCT l.id) FILTER (WHERE l.status_code >= 400) AS errors_count
        FROM generate_series($1::date, ($2::date - INTERVAL '1 day')::date, INTERVAL '1 day') day
        LEFT JOIN conversations c ON c.created_at::date = day::date
        LEFT JOIN messages m ON m.created_at::date = day::date
        LEFT JOIN file_metadata f ON f.deleted_at IS NULL AND f.created_at::date = day::date
        LEFT JOIN operation_logs l ON l.created_at::date = day::date
        GROUP BY day
        ORDER BY day
        """,
        start,
        end_exclusive,
    )

    by_day = {str(row["date"]): row for row in rows}
    series = []
    cursor = start_date
    while cursor <= end_date:
        key = cursor.isoformat()
        row = by_day.get(key)
        series.append(
            {
                "date": key,
                "conversations": _int(_row_value(row, "conversations")),
                "messages": _int(_row_value(row, "messages")),
                "tokens_used": _int(_row_value(row, "tokens_used")),
                "avg_latency_ms": _int(_row_value(row, "avg_latency_ms")),
                "files_uploaded": _int(_row_value(row, "files_uploaded")),
                "active_users": _int(_row_value(row, "active_users")),
                "errors_count": _int(_row_value(row, "errors_count")),
            }
        )
        cursor += timedelta(days=1)

    return Envelope.success(
        data={
            "granularity": granularity,
            "series": series,
            "period": {"start_date": start_date.isoformat(), "end_date": end_date.isoformat()},
        }
    )


@router.get("/stats/users")
async def user_stats(
    start_date: date = Query(...),
    end_date: date = Query(...),
    limit: int = Query(10, ge=1, le=100),
    sort_by: Literal["tokens_used", "conversations", "messages"] = "tokens_used",
    current_user: dict = Depends(get_current_user),
):
    denied = _require_admin(current_user)
    if denied:
        return denied

    start, end_exclusive = _date_bounds(start_date, end_date)
    order_columns = {
        "tokens_used": "tokens_used",
        "conversations": "conversations",
        "messages": "messages",
    }
    order_column = order_columns[sort_by]
    pool = await get_pool()
    rows = await pool.fetch(
        f"""
        SELECT
            u.id::text AS user_id,
            u.username,
            u.email,
            COUNT(DISTINCT c.id) AS conversations,
            COUNT(DISTINCT m.id) AS messages,
            COALESCE(SUM(m.total_tokens), 0) AS tokens_used,
            COUNT(DISTINCT f.id) AS files_uploaded,
            COALESCE(AVG(m.latency_ms), 0)::INTEGER AS avg_latency_ms,
            MAX(COALESCE(m.created_at, c.updated_at, f.created_at, u.last_login_at)) AS last_active_at
        FROM users u
        LEFT JOIN conversations c
            ON c.user_id = u.id AND c.created_at >= $1 AND c.created_at < $2
        LEFT JOIN messages m
            ON m.conversation_id = c.id AND m.created_at >= $1 AND m.created_at < $2
        LEFT JOIN file_metadata f
            ON f.uploaded_by = u.id
            AND f.deleted_at IS NULL
            AND f.created_at >= $1
            AND f.created_at < $2
        GROUP BY u.id, u.username, u.email
        ORDER BY {order_column} DESC, u.username ASC
        LIMIT $3
        """,
        start,
        end_exclusive,
        limit,
    )

    return Envelope.success(
        data={
            "users": [
                {
                    "user_id": row["user_id"],
                    "username": row["username"],
                    "email": row["email"],
                    "conversations": _int(row["conversations"]),
                    "messages": _int(row["messages"]),
                    "tokens_used": _int(row["tokens_used"]),
                    "files_uploaded": _int(row["files_uploaded"]),
                    "avg_latency_ms": _int(row["avg_latency_ms"]),
                    "last_active_at": (
                        row["last_active_at"].isoformat() if row["last_active_at"] else None
                    ),
                }
                for row in rows
            ]
        }
    )
