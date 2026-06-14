"""
CloudRAG-Hub Backend
纯 BFF 代理层: 接收前端请求, 转发至 Dify API, 流式透传响应。
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import get_settings
from .routes import routers


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://localhost:3000", "http://localhost:8081"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    for router in routers:
        app.include_router(router)

    @app.get("/health")
    async def health():
        return {"status": "healthy", "service": settings.app_name, "version": settings.app_version}

    return app


app = create_app()
