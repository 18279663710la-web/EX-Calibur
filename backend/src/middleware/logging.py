import time
import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request


class AuditLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        request.state.request_id = str(uuid.uuid4())
        start = time.time()
        response = await call_next(request)
        response.headers["X-Request-ID"] = request.state.request_id
        response.headers["X-Latency-Ms"] = str(int((time.time() - start) * 1000))
        return response


async def log_request_to_db(pool, log_entry: dict):
    try:
        async with pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO operation_logs
                   (id, user_id, request_id, method, path, status_code,
                    latency_ms, ip_address, user_agent, token_used, error_message)
                   VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)""",
                str(uuid.uuid4()),
                log_entry.get("user_id"),
                log_entry.get("request_id"),
                log_entry.get("method"),
                log_entry.get("path"),
                log_entry.get("status_code"),
                log_entry.get("latency_ms"),
                log_entry.get("ip_address"),
                log_entry.get("user_agent"),
                log_entry.get("token_used", False),
                log_entry.get("error_message"),
            )
    except Exception:
        pass
