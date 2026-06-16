"""Sync local knowledge files into a Dify knowledge dataset.

The script is intentionally independent from the CloudRAG backend. It treats
the backend as a gateway for chat only, while this file handles scheduled
document shipping from ./knowledge to Dify.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import mimetypes
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Protocol

import requests
from docx import Document
from PyPDF2 import PdfReader


PROJECT_ROOT = Path(__file__).resolve().parent

# You can edit these constants directly, or set the matching environment vars.
DIFY_BASE_URL = os.getenv("DIFY_BASE_URL", "http://localhost/v1")
DATASET_API_KEY = os.getenv("DIFY_DATASET_API_KEY", "")
DATASET_ID = os.getenv("DIFY_DATASET_ID", "")
LOCAL_FILE_DIR = Path(os.getenv("LOCAL_FILE_DIR", PROJECT_ROOT / "knowledge"))
SYNC_LEDGER_PATH = Path(os.getenv("SYNC_LEDGER_PATH", PROJECT_ROOT / "sync_ledger.json"))
STRUCTURED_MARKDOWN_DIR = Path(
    os.getenv("STRUCTURED_MARKDOWN_DIR", PROJECT_ROOT / "structured_markdown")
)
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1")
DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")

UPLOAD_TIMEOUT_SECONDS = int(os.getenv("DIFY_DATASET_UPLOAD_TIMEOUT", "300"))
CLEANED_MARKDOWN_MIN_BODY_SIMILARITY = float(
    os.getenv("CLEANED_MARKDOWN_MIN_BODY_SIMILARITY", "0.95")
)
PIPELINE_VERSION = os.getenv("RAG_SYNC_PIPELINE_VERSION", "deepseek-preserve-v2")
SUPPORTED_EXTENSIONS = {
    ".csv",
    ".doc",
    ".docx",
    ".htm",
    ".html",
    ".markdown",
    ".md",
    ".mdx",
    ".pdf",
    ".properties",
    ".txt",
    ".vtt",
    ".xls",
    ".xlsx",
}


class ConfigurationError(RuntimeError):
    """Raised when a real sync cannot start because required config is absent."""


class Cleaner(Protocol):
    def clean(self, raw_text: str) -> str:
        """Return cleaned markdown text."""


@dataclass(frozen=True)
class FileState:
    path: Path
    relative_path: str
    sha256: str
    size: int
    modified_at: float


@dataclass(frozen=True)
class SyncResult:
    scanned: int
    to_upload: int
    uploaded: int
    skipped: int
    failed: int


@dataclass(frozen=True)
class UploadCandidate:
    source: FileState
    upload_path: Path
    ledger_key: str
    generated_relative_path: str | None = None


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def normalize_base_url(base_url: str) -> str:
    return base_url.rstrip("/")


def upload_url(base_url: str, dataset_id: str) -> str:
    return f"{normalize_base_url(base_url)}/datasets/{dataset_id}/document/create-by-file"


def load_ledger(ledger_path: Path) -> dict[str, Any]:
    if not ledger_path.exists():
        return {"files": {}}

    with ledger_path.open("r", encoding="utf-8") as file:
        data = json.load(file)

    if not isinstance(data, dict):
        return {"files": {}}
    if not isinstance(data.get("files"), dict):
        data["files"] = {}
    return data


def save_ledger(ledger_path: Path, ledger: dict[str, Any]) -> None:
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    with ledger_path.open("w", encoding="utf-8") as file:
        json.dump(ledger, file, ensure_ascii=False, indent=2)
        file.write("\n")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def describe_file(path: Path, source_dir: Path) -> FileState:
    stat = path.stat()
    relative_path = path.relative_to(source_dir).as_posix()
    return FileState(
        path=path,
        relative_path=relative_path,
        sha256=sha256_file(path),
        size=stat.st_size,
        modified_at=stat.st_mtime,
    )


def iter_supported_files(source_dir: Path) -> list[FileState]:
    if not source_dir.exists():
        raise FileNotFoundError(f"LOCAL_FILE_DIR does not exist: {source_dir}")
    if not source_dir.is_dir():
        raise NotADirectoryError(f"LOCAL_FILE_DIR is not a directory: {source_dir}")

    files: list[FileState] = []
    for path in sorted(source_dir.rglob("*")):
        if not path.is_file():
            continue
        if path.name.startswith("~$"):
            continue
        if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
            continue
        files.append(describe_file(path, source_dir))
    return files


def needs_upload(file_state: FileState, ledger: dict[str, Any], *, pipeline: str = "direct") -> bool:
    record = ledger.get("files", {}).get(file_state.relative_path)
    if not isinstance(record, dict):
        return True
    if record.get("pipeline", "direct") != pipeline:
        return True
    if pipeline == "deepseek" and record.get("pipeline_version") != PIPELINE_VERSION:
        return True
    return not (
        record.get("status") == "synced"
        and record.get("sha256") == file_state.sha256
        and record.get("size") == file_state.size
    )


def dify_document_payload() -> dict[str, Any]:
    return {
        "indexing_technique": "high_quality",
        "doc_form": "text_model",
        "doc_language": "Chinese",
        "process_rule": {"mode": "automatic"},
    }


def dify_custom_markdown_payload() -> dict[str, Any]:
    return {
        "indexing_technique": "high_quality",
        "doc_form": "text_model",
        "doc_language": "Chinese",
        "process_rule": {
            "mode": "custom",
            "rules": {
                "pre_processing_rules": [
                    {"id": "remove_extra_spaces", "enabled": True},
                    {"id": "remove_urls_emails", "enabled": False},
                ],
                "segmentation": {
                    "separator": "\n## ",
                    "max_tokens": 800,
                }
            },
        },
    }


def add_retrieval_hints(markdown: str, file_name: str) -> str:
    """Add source and section terms so Dify keyword retrieval can anchor on files."""
    if "来源文件：" in markdown:
        return markdown

    document_name = Path(file_name).stem
    lines = markdown.splitlines()
    enhanced: list[str] = []
    for line in lines:
        enhanced.append(line)
        stripped = line.strip()
        if not stripped.startswith("## "):
            continue
        section_title = stripped[3:].strip()
        if not section_title:
            continue
        enhanced.extend(
            [
                f"来源文件：{file_name}",
                f"文档名称：{document_name}",
                f"章节标题：{section_title}",
                f"检索关键词：{' '.join(retrieval_terms(document_name, file_name, section_title))}",
                "",
            ]
        )
    return "\n".join(enhanced)


RETRIEVAL_HINT_PREFIXES = (
    "来源文件：",
    "文档名称：",
    "章节标题：",
    "检索关键词：",
)


def strip_retrieval_hints(markdown: str) -> str:
    return "\n".join(
        line
        for line in markdown.splitlines()
        if not line.strip().startswith(RETRIEVAL_HINT_PREFIXES)
    )


def normalize_body_for_similarity(text: str) -> str:
    text = strip_retrieval_hints(text)
    text = re.sub(r"[#>*_`|\\\-:：,，.。;；!！?？()（）\[\]{}<>《》\"“”'‘’/]+", "", text)
    text = re.sub(r"\s+", "", text)
    return text.lower()


def markdown_body_similarity(source_text: str, markdown: str) -> float:
    """Return how much of the source body is retained in cleaned Markdown.

    The score is source-coverage oriented: retrieval hints and Markdown syntax
    are ignored, and extra section labels do not hide source truncation.
    """

    source = normalize_body_for_similarity(source_text)
    cleaned = normalize_body_for_similarity(markdown)
    if not source and not cleaned:
        return 1.0
    if not source or not cleaned:
        return 0.0
    matcher = SequenceMatcher(None, source, cleaned, autojunk=False)
    matched = sum(block.size for block in matcher.get_matching_blocks())
    return matched / len(source)


def preserved_source_markdown(raw_text: str, file_name: str) -> str:
    """Convert extracted source text to Markdown while preserving every line."""

    lines = [line.rstrip() for line in raw_text.replace("\r\n", "\n").replace("\r", "\n").split("\n")]
    body = "\n".join(lines).strip()
    if not body:
        return f"## {Path(file_name).stem}\n"
    if any(line.lstrip().startswith("#") for line in lines):
        return body + "\n"
    return f"## {Path(file_name).stem}\n\n{body}\n"


def ensure_markdown_body_fidelity(raw_text: str, markdown: str, file_name: str) -> str:
    similarity = markdown_body_similarity(raw_text, markdown)
    if similarity >= CLEANED_MARKDOWN_MIN_BODY_SIMILARITY:
        return markdown

    fallback = preserved_source_markdown(raw_text, file_name)
    fallback_similarity = markdown_body_similarity(raw_text, fallback)
    print(
        "[QUALITY] cleaned markdown body similarity "
        f"{similarity:.2%} below {CLEANED_MARKDOWN_MIN_BODY_SIMILARITY:.0%}; "
        f"using source-preserving fallback ({fallback_similarity:.2%}): {file_name}"
    )
    return fallback


def retrieval_terms(document_name: str, file_name: str, section_title: str) -> list[str]:
    terms = [document_name, file_name, section_title]
    normalized = (
        section_title.replace("(", " ")
        .replace(")", " ")
        .replace("（", " ")
        .replace("）", " ")
        .replace("-", " ")
    )
    for token in normalized.split():
        if len(token) >= 2:
            terms.append(token)
    if "架构设计" in section_title:
        terms.append(section_title.replace("架构设计", "设计"))
        terms.append(section_title.replace("设计", ""))
    if "端" in section_title and "设计" in section_title:
        prefix = section_title.split("设计", 1)[0]
        terms.append(f"{prefix}方案")
        terms.append(f"{prefix}部分")
    combined = f"{document_name} {file_name} {section_title}"
    if "数据投毒" in combined and any(marker in combined for marker in ("数据", "案例", "实例", "结果", "指标")):
        terms.extend(
            [
                "关键数据",
                "案例指标",
                "实验数据",
                "百分比",
                "路牌投毒攻击",
                "量化模型投毒",
                "目标检测平均精度下降",
                "虚假舆情数据",
            ]
        )
    seen: set[str] = set()
    unique_terms: list[str] = []
    for term in terms:
        term = " ".join(term.split())
        if not term or term in seen:
            continue
        seen.add(term)
        unique_terms.append(term)
    return unique_terms


def guess_mime_type(path: Path) -> str:
    if path.suffix.lower() == ".md":
        return "text/markdown"
    if path.suffix.lower() == ".markdown":
        return "text/markdown"
    return mimetypes.guess_type(path.name)[0] or "application/octet-stream"


def extract_docx_text(path: Path) -> str:
    document = Document(path)
    lines = [paragraph.text.strip() for paragraph in document.paragraphs]
    return "\n".join(line for line in lines if line)


def extract_pdf_text(path: Path) -> str:
    reader = PdfReader(str(path))
    pages = []
    for page in reader.pages:
        text = page.extract_text() or ""
        if text.strip():
            pages.append(text.strip())
    return "\n\n".join(pages)


def extract_source_text(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".docx":
        return sanitize_text_for_json(extract_docx_text(path))
    if suffix == ".pdf":
        return sanitize_text_for_json(extract_pdf_text(path))
    if suffix in {".md", ".markdown", ".txt"}:
        return sanitize_text_for_json(path.read_text(encoding="utf-8"))
    raise ConfigurationError(f"DeepSeek pipeline does not support source type: {path.suffix}")


def sanitize_text_for_json(text: str) -> str:
    return text.encode("utf-8", errors="ignore").decode("utf-8")


DEEPSEEK_SYSTEM_PROMPT = """你是一个严谨的学术文档处理专家。请将以下粗略提取的实验报告文本重构成规范的 Markdown 文档。

配置规范：
1. 识别实验结构，并严格使用 `## ` 作为核心一级章节标题（例如：## 实验目的、## 实验原理、## 实验步骤、## 实验数据与结果、## 分析与讨论）。
2. 将文本中散落的实验测试数据和表格信息，智能还原为标准的 Markdown 表格格式（| Header | Header |）。
3. 彻底滤除类似“第 X 页”、“学号：xxx”、“姓名：xxx”、“评卷人”等无关的重复性页眉页脚及打印噪声。
4. 【红线要求】必须保持原始实验数据、代码逻辑和学术结论的绝对完整与真实，严禁润色、篡改、总结或删减核心内容。直接输出 Markdown 正文，切勿包含任何自我解释的提示语或包裹性废话。"""


class DeepSeekCleaner:
    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = DEEPSEEK_BASE_URL,
        model: str = DEEPSEEK_MODEL,
        timeout: int = 180,
        chunk_chars: int = 18000,
    ):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout
        self.chunk_chars = chunk_chars

    def clean(self, raw_text: str) -> str:
        chunks = split_text(raw_text, self.chunk_chars)
        cleaned_chunks = [self._clean_chunk(chunk, index, len(chunks)) for index, chunk in enumerate(chunks, 1)]
        return "\n\n".join(chunk for chunk in cleaned_chunks if chunk.strip())

    def _clean_chunk(self, raw_text: str, index: int, total: int) -> str:
        url = f"{self.base_url}/chat/completions"
        chunk_note = f"（第 {index}/{total} 段）" if total > 1 else ""
        response = requests.post(
            url,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": self.model,
                "messages": [
                    {"role": "system", "content": DEEPSEEK_SYSTEM_PROMPT},
                    {
                        "role": "user",
                        "content": f"请对以下原始实验报告内容{chunk_note}进行结构化清洗：\n\n{raw_text}",
                    },
                ],
                "temperature": 0.1,
                "stream": False,
            },
            timeout=self.timeout,
        )
        if response.status_code >= 400:
            raise requests.HTTPError(
                f"DeepSeek HTTP {response.status_code} {response.reason}: {response.text[:1000]}",
                response=response,
            )
        payload = response.json()
        choices = payload.get("choices")
        if not choices or not isinstance(choices, list):
            raise RuntimeError("DeepSeek response missing choices")
        message = choices[0].get("message") if isinstance(choices[0], dict) else {}
        content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content, str) or not content.strip():
            raise RuntimeError("DeepSeek response missing cleaned markdown")
        return content.strip()


def split_text(text: str, chunk_chars: int) -> list[str]:
    text = text.strip()
    if not text:
        return [""]
    if len(text) <= chunk_chars:
        return [text]

    chunks: list[str] = []
    current: list[str] = []
    current_len = 0
    for paragraph in text.splitlines():
        piece = paragraph.rstrip()
        piece_len = len(piece) + 1
        if current and current_len + piece_len > chunk_chars:
            chunks.append("\n".join(current).strip())
            current = []
            current_len = 0
        if piece_len > chunk_chars:
            for start in range(0, len(piece), chunk_chars):
                if current:
                    chunks.append("\n".join(current).strip())
                    current = []
                    current_len = 0
                chunks.append(piece[start : start + chunk_chars].strip())
            continue
        current.append(piece)
        current_len += piece_len
    if current:
        chunks.append("\n".join(current).strip())
    return [chunk for chunk in chunks if chunk]


def markdown_output_path(file_state: FileState, archive_dir: Path) -> Path:
    relative = Path(file_state.relative_path).with_suffix(".md")
    return archive_dir / relative


def build_upload_candidates(
    pending: list[FileState],
    *,
    pipeline: str,
    archive_dir: Path,
    cleaner: Cleaner | None,
    ledger: dict[str, Any],
) -> list[UploadCandidate]:
    if pipeline == "direct":
        return [
            UploadCandidate(
                source=file_state,
                upload_path=file_state.path,
                ledger_key=file_state.relative_path,
            )
            for file_state in pending
        ]

    if pipeline != "deepseek":
        raise ConfigurationError(f"Unsupported pipeline: {pipeline}")

    if cleaner is None:
        raise ConfigurationError("Missing required config for DeepSeek pipeline: DEEPSEEK_API_KEY")

    candidates: list[UploadCandidate] = []
    for file_state in pending:
        placeholder = UploadCandidate(
            source=file_state,
            upload_path=file_state.path,
            ledger_key=file_state.relative_path,
        )
        if file_state.path.suffix.lower() not in {".docx", ".pdf", ".md", ".markdown", ".txt"}:
            print(f"[SKIP] DeepSeek pipeline does not handle this file: {file_state.relative_path}")
            continue
        try:
            print(f"[CLEAN] extracting source text: {file_state.relative_path}")
            raw_text = extract_source_text(file_state.path)
            print(f"[CLEAN] requesting DeepSeek structured markdown: {file_state.relative_path}")
            markdown = cleaner.clean(raw_text)
            markdown = ensure_markdown_body_fidelity(raw_text, markdown, file_state.path.name)
            output_path = markdown_output_path(file_state, archive_dir)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(
                add_retrieval_hints(markdown, output_path.name),
                encoding="utf-8",
            )
        except Exception as exc:
            record_failure(ledger, placeholder, exc)
            print(f"[FAIL] clean {file_state.relative_path}: {exc}")
            continue
        candidates.append(
            UploadCandidate(
                source=file_state,
                upload_path=output_path,
                ledger_key=file_state.relative_path,
                generated_relative_path=output_path.relative_to(archive_dir).as_posix(),
            )
        )
    return candidates


def upload_file_to_dify(
    upload_path: Path,
    *,
    base_url: str,
    dataset_api_key: str,
    dataset_id: str,
    session: requests.Session,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    headers = {"Authorization": f"Bearer {dataset_api_key}"}
    data = {"data": json.dumps(payload or dify_document_payload(), ensure_ascii=False)}
    mime_type = guess_mime_type(upload_path)

    with upload_path.open("rb") as file:
        response = session.post(
            upload_url(base_url, dataset_id),
            headers=headers,
            data=data,
            files={"file": (upload_path.name, file, mime_type)},
            timeout=UPLOAD_TIMEOUT_SECONDS,
        )
    if response.status_code >= 400:
        raise requests.HTTPError(
            f"{response.status_code} {response.reason}: {response.text[:1000]}",
            response=response,
        )
    return response.json()


def parse_document_id(response_payload: dict[str, Any]) -> str | None:
    document = response_payload.get("document")
    if isinstance(document, dict):
        value = document.get("id")
        return value if isinstance(value, str) else None
    value = response_payload.get("id")
    return value if isinstance(value, str) else None


def record_success(
    ledger: dict[str, Any],
    candidate: UploadCandidate,
    response_payload: dict[str, Any],
    *,
    pipeline: str,
) -> None:
    file_state = candidate.source
    record = {
        "status": "synced",
        "sha256": file_state.sha256,
        "size": file_state.size,
        "modified_at": file_state.modified_at,
        "synced_at": utc_now_iso(),
        "document_id": parse_document_id(response_payload),
        "batch": response_payload.get("batch"),
        "pipeline": pipeline,
    }
    if pipeline == "deepseek":
        record["pipeline_version"] = PIPELINE_VERSION
    if candidate.generated_relative_path:
        record["generated_file"] = candidate.generated_relative_path
    ledger.setdefault("files", {})[candidate.ledger_key] = record


def record_failure(ledger: dict[str, Any], candidate: UploadCandidate, error: Exception) -> None:
    file_state = candidate.source
    previous = ledger.setdefault("files", {}).get(candidate.ledger_key, {})
    if not isinstance(previous, dict):
        previous = {}
    previous.update(
        {
            "status": "failed",
            "sha256": file_state.sha256,
            "size": file_state.size,
            "modified_at": file_state.modified_at,
            "last_error": str(error),
            "failed_at": utc_now_iso(),
        }
    )
    if candidate.generated_relative_path:
        previous["generated_file"] = candidate.generated_relative_path
    ledger["files"][candidate.ledger_key] = previous


def validate_config(base_url: str, dataset_api_key: str, dataset_id: str) -> None:
    missing = []
    if not base_url:
        missing.append("DIFY_BASE_URL")
    if not dataset_api_key:
        missing.append("DIFY_DATASET_API_KEY")
    if not dataset_id:
        missing.append("DIFY_DATASET_ID")
    if missing:
        raise ConfigurationError(
            "Missing required config for real sync: " + ", ".join(missing)
        )


def run_sync(
    *,
    source_dir: Path = LOCAL_FILE_DIR,
    ledger_path: Path = SYNC_LEDGER_PATH,
    base_url: str = DIFY_BASE_URL,
    dataset_api_key: str = DATASET_API_KEY,
    dataset_id: str = DATASET_ID,
    dry_run: bool = False,
    session: requests.Session | None = None,
    archive_dir: Path = STRUCTURED_MARKDOWN_DIR,
    deepseek_api_key: str = DEEPSEEK_API_KEY,
    deepseek_base_url: str = DEEPSEEK_BASE_URL,
    deepseek_model: str = DEEPSEEK_MODEL,
    pipeline: str = "direct",
    cleaner: Cleaner | None = None,
) -> SyncResult:
    files = iter_supported_files(source_dir)
    ledger = load_ledger(ledger_path)
    pending = [
        file_state for file_state in files if needs_upload(file_state, ledger, pipeline=pipeline)
    ]
    skipped = len(files) - len(pending)

    if dry_run:
        for file_state in pending:
            print(f"[DRY-RUN] would upload: {file_state.relative_path}")
        print(
            f"[DRY-RUN] scanned={len(files)} to_upload={len(pending)} "
            f"skipped={skipped}"
        )
        return SyncResult(
            scanned=len(files),
            to_upload=len(pending),
            uploaded=0,
            skipped=skipped,
            failed=0,
        )

    validate_config(base_url, dataset_api_key, dataset_id)
    if pipeline == "deepseek" and cleaner is None:
        if not deepseek_api_key:
            raise ConfigurationError(
                "Missing required config for DeepSeek pipeline: DEEPSEEK_API_KEY"
            )
        cleaner = DeepSeekCleaner(
            api_key=deepseek_api_key,
            base_url=deepseek_base_url,
            model=deepseek_model,
        )

    active_session = session or requests.Session()
    candidates = build_upload_candidates(
        pending,
        pipeline=pipeline,
        archive_dir=archive_dir,
        cleaner=cleaner,
        ledger=ledger,
    )
    uploaded = 0
    failed = 0
    upload_payload = (
        dify_custom_markdown_payload() if pipeline == "deepseek" else dify_document_payload()
    )
    for candidate in candidates:
        try:
            print(f"[SYNC] uploading: {candidate.upload_path.name}")
            response_payload = upload_file_to_dify(
                candidate.upload_path,
                base_url=base_url,
                dataset_api_key=dataset_api_key,
                dataset_id=dataset_id,
                session=active_session,
                payload=upload_payload,
            )
        except Exception as exc:  # Keep the rest of the batch moving.
            failed += 1
            record_failure(ledger, candidate, exc)
            print(f"[FAIL] {candidate.ledger_key}: {exc}")
            continue

        uploaded += 1
        record_success(ledger, candidate, response_payload, pipeline=pipeline)
        save_ledger(ledger_path, ledger)
        print(f"[OK] {candidate.ledger_key}")

    save_ledger(ledger_path, ledger)
    print(
        f"[DONE] scanned={len(files)} uploaded={uploaded} "
        f"skipped={skipped} failed={failed}"
    )
    return SyncResult(
        scanned=len(files),
        to_upload=len(pending),
        uploaded=uploaded,
        skipped=skipped,
        failed=failed,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Sync ./knowledge documents to a Dify knowledge dataset."
    )
    parser.add_argument("--dry-run", action="store_true", help="List pending files only.")
    parser.add_argument(
        "--source-dir",
        type=Path,
        default=LOCAL_FILE_DIR,
        help="Local directory containing knowledge files.",
    )
    parser.add_argument(
        "--ledger",
        type=Path,
        default=SYNC_LEDGER_PATH,
        help="JSON ledger path.",
    )
    parser.add_argument("--base-url", default=DIFY_BASE_URL, help="Dify API base URL.")
    parser.add_argument(
        "--dataset-id",
        default=DATASET_ID,
        help="Dify dataset ID. Can also be set via DIFY_DATASET_ID.",
    )
    parser.add_argument(
        "--pipeline",
        choices=["direct", "deepseek"],
        default=os.getenv("RAG_SYNC_PIPELINE", "direct"),
        help="direct uploads source files; deepseek cleans .docx files to markdown first.",
    )
    parser.add_argument(
        "--archive-dir",
        type=Path,
        default=STRUCTURED_MARKDOWN_DIR,
        help="Directory for DeepSeek-cleaned markdown files.",
    )
    parser.add_argument(
        "--deepseek-base-url",
        default=DEEPSEEK_BASE_URL,
        help="DeepSeek OpenAI-compatible API base URL.",
    )
    parser.add_argument(
        "--deepseek-model",
        default=DEEPSEEK_MODEL,
        help="DeepSeek model name.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        run_sync(
            source_dir=args.source_dir,
            ledger_path=args.ledger,
            base_url=args.base_url,
            dataset_api_key=DATASET_API_KEY,
            dataset_id=args.dataset_id,
            dry_run=args.dry_run,
            archive_dir=args.archive_dir,
            deepseek_api_key=DEEPSEEK_API_KEY,
            deepseek_base_url=args.deepseek_base_url,
            deepseek_model=args.deepseek_model,
            pipeline=args.pipeline,
        )
    except ConfigurationError as exc:
        print(f"[CONFIG] {exc}")
        return 2
    except Exception as exc:
        print(f"[ERROR] {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
