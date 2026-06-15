"""
CloudRAG-Hub Backend Application
基于 FastAPI 的 BFF 层服务
成员 3 (后端核心) & 成员 5 (大数据工程师)
"""

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from .config import get_settings
from .database import get_pool, close_pool, ensure_architecture_schema
from .middleware.logging import AuditLoggingMiddleware, log_request_to_db
from .routes import routers
from .services.channels import get_channel_manager


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 启动：确保上传目录存在
    settings = get_settings()
    os.makedirs(settings.upload_dir, exist_ok=True)
    await ensure_architecture_schema(await get_pool())
    await get_channel_manager().startup()
    yield
    # 关闭：释放数据库连接池
    await close_pool()


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        lifespan=lifespan,
    )

    # CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://localhost:3000", "http://localhost:8081"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # 审计日志中间件
    app.add_middleware(AuditLoggingMiddleware)

    # 挂载后台日志写入函数
    app.extra["log_to_db"] = log_request_to_db

    # 注册路由
    for router in routers:
        app.include_router(router)

    @app.get("/health")
    async def health():
        return {"status": "healthy", "service": settings.app_name, "version": settings.app_version}

    # Architecture spec: WebSocket endpoint for pipeline progress
    @app.websocket("/ws/pipeline-status")
    async def pipeline_ws(websocket: WebSocket):
        await websocket.accept()
        try:
            import asyncio as _asyncio
            from .services.pipeline_store import load_task

            # Client sends task_id to subscribe
            data = await websocket.receive_text()
            task_id = data.strip() if data else ""
            last_stage = ""
            last_status = ""

            while True:
                task = load_task(task_id) if task_id else None
                if task:
                    stage = task.get("current_stage", "")
                    status = task.get("overall_status", "")
                    if stage != last_stage or status != last_status:
                        await websocket.send_json({
                            "task_id": task_id,
                            "current_stage": stage,
                            "overall_status": status,
                            "stages": task.get("stages", {}),
                        })
                        last_stage, last_status = stage, status
                        if status in ("completed", "failed"):
                            await _asyncio.sleep(1)
                            await websocket.close()
                            return
                await _asyncio.sleep(1)
        except Exception:
            pass

    return app


app = create_app()
