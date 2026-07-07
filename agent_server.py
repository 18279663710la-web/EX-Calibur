from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import shutil
import sys
from pathlib import Path
from typing import List
from urllib.parse import quote

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

PROJECT_ROOT = Path(__file__).resolve().parent
BACKEND_ROOT = PROJECT_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from src.services.file_matcher import resolve_best_match, search_knowledge_files

DEFAULT_KNOWLEDGE_DIR = PROJECT_ROOT / "knowledge"


def get_knowledge_dir() -> Path:
    return Path(os.getenv("AGENT_KNOWLEDGE_DIR", DEFAULT_KNOWLEDGE_DIR)).resolve()


def get_agent_port() -> int:
    return int(os.getenv("AGENT_PORT", "8090"))


def get_public_base_url() -> str:
    default = f"http://localhost:{get_agent_port()}"
    return os.getenv("AGENT_PUBLIC_BASE_URL", default).rstrip("/")


def get_download_secret() -> bytes:
    secret = os.getenv("AGENT_DOWNLOAD_SECRET")
    if not secret:
        secret = str(get_knowledge_dir())
    return secret.encode("utf-8")


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

    knowledge_dir = ensure_knowledge_dir()
    requested_lower = requested.lower()
    requested_stem_lower = Path(requested).stem.lower()
    for path in _iter_knowledge_files():
        if path.name.lower() == requested_lower or path.stem.lower() == requested_stem_lower:
            return path

    return resolve_best_match(requested, knowledge_dir=knowledge_dir)


def _is_within_knowledge_dir(path: Path) -> bool:
    try:
        path.resolve().relative_to(ensure_knowledge_dir())
        return True
    except ValueError:
        return False


def _encode_payload(payload: dict[str, str]) -> str:
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _decode_payload(value: str) -> dict[str, str] | None:
    try:
        padded = value + "=" * (-len(value) % 4)
        raw = base64.urlsafe_b64decode(padded.encode("ascii"))
        payload = json.loads(raw.decode("utf-8"))
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    return {str(key): str(item) for key, item in payload.items()}


def _sign_payload(payload: str) -> str:
    return hmac.new(get_download_secret(), payload.encode("ascii"), hashlib.sha256).hexdigest()


def create_download_token(path: Path) -> str:
    payload = _encode_payload({"path": str(path.resolve()), "filename": path.name})
    return f"{payload}.{_sign_payload(payload)}"


def resolve_download_token(token: str) -> Path | None:
    try:
        payload, signature = token.rsplit(".", 1)
    except ValueError:
        return None
    if not hmac.compare_digest(signature, _sign_payload(payload)):
        return None
    data = _decode_payload(payload)
    if not data or "path" not in data:
        return None
    return Path(data["path"]).resolve()


def build_download_url(path: Path) -> str:
    return f"{get_public_base_url()}/files/{create_download_token(path)}"


def search_files(keyword: str, top_k: int = 5) -> list[dict[str, object]]:
    matches = search_knowledge_files(
        keyword,
        knowledge_dir=ensure_knowledge_dir(),
        top_k=top_k,
    )
    return [
        {
            "filename": item["file_name"],
            "path": item["path"],
            "score": item["score"],
        }
        for item in matches
    ]


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

    target_path = target_path.resolve()
    if not _is_within_knowledge_dir(target_path):
        raise HTTPException(status_code=403, detail="文件不在知识库目录内")

    download_url = build_download_url(target_path)
    message = f"文件下载地址：\n{download_url}"
    return {
        "status": "success",
        "filename": target_path.name,
        "requested_filename": req.filename,
        "size_bytes": target_path.stat().st_size,
        "download_url": download_url,
        "message": message,
        "markdown": message,
    }


@app.get("/files/{token}")
async def download_file(token: str) -> FileResponse:
    target_path = resolve_download_token(token)
    if not target_path:
        raise HTTPException(status_code=404, detail="下载链接无效")
    if not _is_within_knowledge_dir(target_path):
        raise HTTPException(status_code=403, detail="文件不在知识库目录内")
    if not target_path.is_file():
        raise HTTPException(status_code=404, detail="文件不存在")

    headers = {
        "Content-Disposition": f"attachment; filename*=utf-8''{quote(target_path.name)}",
    }
    return FileResponse(target_path, filename=target_path.name, headers=headers)


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
