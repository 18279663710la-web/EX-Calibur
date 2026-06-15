from .auth import router as auth_router
from .pipeline import router as pipeline_router
from .files import router as files_router
from .dashboard import router as dashboard_router
from .chat import router as chat_router
from .clawbot import router as clawbot_router
from .channels import router as channels_router

routers = [
    auth_router,
    pipeline_router,
    files_router,
    dashboard_router,
    chat_router,
    clawbot_router,
    channels_router,
]
