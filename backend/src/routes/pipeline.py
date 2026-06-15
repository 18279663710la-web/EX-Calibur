from fastapi import APIRouter

router = APIRouter(prefix="/api/v1/pipeline", tags=["Pipeline"])


@router.get("/status/{task_id}")
async def pipeline_status(task_id: str):
    return {"task_id": task_id, "status": "unknown"}
