from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import List

from fastapi import FastAPI, File, HTTPException, UploadFile
from pydantic import BaseModel
from rapidfuzz import fuzz


PROJECT_ROOT = Path(__file__).resolve().parent
DEFAULT_KNOWLEDGE_DIR = PROJECT_ROOT / "knowledge"


def get_knowledge_dir() -> Path:
    return Path(os.getenv("AGENT_KNOWLEDGE_DIR", DEFAULT_KNOWLEDGE_DIR)).resolve()


def get_agent_port() -> int:
    return int(os.getenv("AGENT_PORT", "8090"))


def ensure_knowledge_dir() -> Path:
    knowledge_dir = get_knowledge_dir()
    knowledge_dir.mkdir(parents=True, exist_ok=True)
    return knowledge_dir


app = FastAPI(title="CloudRAG Agent File Service")


class SearchRequest(BaseModel):
    keyword: str
    top_k: int = 5


class OpenRequest(BaseModel):
    filename: str


def _iter_knowledge_files() -> list[Path]:
    knowledge_dir = ensure_knowledge_dir()
    files: list[Path] = []
    for root, _, names in os.walk(knowledge_dir):
        files.extend(Path(root) / name for name in names)
    return files


def _requested_basename(filename: str) -> str:
    return Path(str(filename or "").replace("\\", "/")).name


def resolve_file(filename: str) -> Path | None:
    requested = _requested_basename(filename)
    if not requested:
        return None

    files = _iter_knowledge_files()
    for path in files:
        if path.name == requested:
            return path

    requested_lower = requested.lower()
    for path in files:
        if path.name.lower() == requested_lower:
            return path

    matches = [
        (fuzz.partial_ratio(requested_lower, path.name.lower()), path)
        for path in files
    ]
    if not matches:
        return None
    score, path = max(matches, key=lambda item: item[0])
    return path if score >= 85 else None


def search_files(keyword: str, top_k: int = 5) -> list[dict[str, object]]:
    knowledge_dir = ensure_knowledge_dir()
    results: list[dict[str, object]] = []

    for root, _, files in os.walk(knowledge_dir):
        for filename in files:
            score = fuzz.partial_ratio(keyword.lower(), filename.lower())
            if score > 30:
                path = Path(root) / filename
                results.append(
                    {
                        "filename": filename,
                        "path": str(path),
                        "score": score,
                    }
                )

    results.sort(key=lambda item: item["score"], reverse=True)
    return results[:top_k]


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "knowledge_dir": str(ensure_knowledge_dir())}


@app.post("/search")
async def search(req: SearchRequest) -> dict[str, object]:
    files = search_files(req.keyword, req.top_k)
    return {"keyword": req.keyword, "count": len(files), "files": files}


@app.post("/open")
async def open_file(req: OpenRequest) -> dict[str, object]:
    target_path = resolve_file(req.filename)

    if not target_path:
        raise HTTPException(status_code=404, detail="文件不存在")

    try:
        if hasattr(os, "startfile"):
            os.startfile(target_path)  # type: ignore[attr-defined]
            return {
                "status": "success",
                "opened": True,
                "open_method": "os.startfile",
                "filename": target_path.name,
                "requested_filename": req.filename,
                "path": str(target_path),
            }
        return {
            "status": "success",
            "opened": False,
            "open_method": "path_returned",
            "filename": target_path.name,
            "requested_filename": req.filename,
            "path": str(target_path),
            "message": "Native file opening is unavailable in this runtime; use the returned path.",
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/upload")
async def upload_files(files: List[UploadFile] = File(...)) -> dict[str, object]:
    knowledge_dir = ensure_knowledge_dir()
    uploaded_titles: list[str] = []
    failed_files: list[dict[str, str]] = []

    for file in files:
        file_location = knowledge_dir / Path(file.filename).name
        try:
            with file_location.open("wb") as file_object:
                shutil.copyfileobj(file.file, file_object)
            uploaded_titles.append(file.filename)
        except Exception as exc:
            failed_files.append({"filename": file.filename, "error": str(exc)})

    return {
        "status": "success" if not failed_files else "partial_success",
        "uploaded_count": len(uploaded_titles),
        "uploaded_files": uploaded_titles,
        "failed_files": failed_files,
        "message": f"成功入库 {len(uploaded_titles)} 个文件。"
        + (f" 失败 {len(failed_files)} 个。" if failed_files else ""),
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=get_agent_port())
