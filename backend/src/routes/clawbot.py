from fastapi import APIRouter

router = APIRouter(prefix="/api/v1/clawbot", tags=["Clawbot"])


@router.get("/status")
async def clawbot_status():
    return {"status": "ok"}
