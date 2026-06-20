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
from docx.document import Document as DocxDocument
from docx.oxml.table import CT_Tbl
from docx.oxml.text.paragraph import CT_P
from docx.table import Table
from docx.text.paragraph import Paragraph
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
DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-v4-pro")

UPLOAD_TIMEOUT_SECONDS = int(os.getenv("DIFY_DATASET_UPLOAD_TIMEOUT", "300"))
CLEANED_MARKDOWN_MIN_BODY_SIMILARITY = float(
    os.getenv("CLEANED_MARKDOWN_MIN_BODY_SIMILARITY", "0.95")
)
PIPELINE_VERSION = os.getenv("RAG_SYNC_PIPELINE_VERSION", "deepseek-preserve-v3")
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


def dataset_documents_url(base_url: str, dataset_id: str) -> str:
    return f"{normalize_base_url(base_url)}/datasets/{dataset_id}/documents"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def normalize_base_url(base_url: str) -> str:
    return base_url.rstrip("/")


def upload_url(base_url: str, dataset_id: str) -> str:
    return f"{normalize_base_url(base_url)}/datasets/{dataset_id}/document/create-by-file"


def document_url(base_url: str, dataset_id: str, document_id: str) -> str:
    return f"{normalize_base_url(base_url)}/datasets/{dataset_id}/documents/{document_id}"


def load_ledger(ledger_path: Path) -> dict[str, Any]:
    if not ledger_path.exists():
        return {"files": {}, "whitelist": {}}

    with ledger_path.open("r", encoding="utf-8") as file:
        data = json.load(file)

    if not isinstance(data, dict):
        return {"files": {}, "whitelist": {}}
    if not isinstance(data.get("files"), dict):
        data["files"] = {}
    if not isinstance(data.get("whitelist"), dict):
        data["whitelist"] = {}
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
    if record.get("status") != "synced":
        return True
    if record.get("pipeline", "direct") != pipeline:
        return True
    if pipeline == "deepseek" and record.get("pipeline_version") != PIPELINE_VERSION:
        return True
    if not record.get("document_id"):
        return True
    return not (
        record.get("sha256") == file_state.sha256
        and record.get("size") == file_state.size
    )


def expected_remote_name(relative_path: str, pipeline: str) -> str:
    path = Path(relative_path)
    if pipeline == "deepseek":
        return path.with_suffix(".md").name
    return path.name


def build_remote_documents_by_name(remote_documents: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    documents_by_name: dict[str, dict[str, Any]] = {}
    for document in remote_documents:
        if not isinstance(document, dict):
            continue
        document_id = document.get("id")
        name = document.get("name") or document.get("data_source_info", {}).get("upload_file", {}).get("name")
        if not isinstance(document_id, str) or not isinstance(name, str) or not name:
            continue
        documents_by_name[name] = {
            "document_id": document_id,
            "remote_name": name,
            "indexing_status": document.get("indexing_status"),
        }
    return documents_by_name


def list_dataset_documents(
    *,
    base_url: str,
    dataset_api_key: str,
    dataset_id: str,
    session: requests.Session,
) -> list[dict[str, Any]]:
    headers = {"Authorization": f"Bearer {dataset_api_key}"}
    page = 1
    documents: list[dict[str, Any]] = []
    while True:
        response = session.get(
            dataset_documents_url(base_url, dataset_id),
            headers=headers,
            params={"page": page, "limit": 100},
            timeout=UPLOAD_TIMEOUT_SECONDS,
        )
        if response.status_code >= 400:
            raise requests.HTTPError(
                f"{response.status_code} {response.reason}: {response.text[:1000]}",
                response=response,
            )
        payload = response.json()
        batch = payload.get("data")
        if not isinstance(batch, list) or not batch:
            break
        documents.extend(item for item in batch if isinstance(item, dict))
        if len(batch) < 100:
            break
        page += 1
    return documents


def clear_dataset_documents(
    *,
    base_url: str,
    dataset_api_key: str,
    dataset_id: str,
    remote_documents: list[dict[str, Any]],
    session: requests.Session,
) -> int:
    headers = {"Authorization": f"Bearer {dataset_api_key}"}
    deleted = 0
    for document in remote_documents:
        document_id = document.get("id") if isinstance(document, dict) else None
        if not isinstance(document_id, str) or not document_id:
            continue
        response = session.delete(
            document_url(base_url, dataset_id, document_id),
            headers=headers,
            timeout=UPLOAD_TIMEOUT_SECONDS,
        )
        if response.status_code >= 400:
            raise requests.HTTPError(
                f"{response.status_code} {response.reason}: {response.text[:1000]}",
                response=response,
            )
        deleted += 1
        print(f"[CLEAR] deleted Dify document: {document_id}")
    return deleted


def refresh_ledger_whitelist(
    ledger: dict[str, Any],
    files: list[FileState],
    remote_documents: list[dict[str, Any]],
    *,
    pipeline: str,
) -> None:
    remote_by_name = build_remote_documents_by_name(remote_documents)
    remote_name_counts: dict[str, int] = {}
    for file_state in files:
        remote_name = expected_remote_name(file_state.relative_path, pipeline)
        remote_name_counts[remote_name] = remote_name_counts.get(remote_name, 0) + 1

    whitelist: dict[str, dict[str, Any]] = {}
    ledger["whitelist"] = whitelist
    known_files = {file_state.relative_path for file_state in files}
    file_records = ledger.setdefault("files", {})

    for file_state in files:
        record = file_records.get(file_state.relative_path, {})
        if not isinstance(record, dict):
            record = {}
        remote_name = expected_remote_name(file_state.relative_path, pipeline)
        whitelist_entry = (
            remote_by_name.get(remote_name)
            if remote_name_counts.get(remote_name, 0) == 1
            else None
        )
        if whitelist_entry:
            pipeline_version_matches = (
                pipeline != "deepseek"
                or record.get("pipeline_version") == PIPELINE_VERSION
            )
            if not pipeline_version_matches:
                record.update(
                    {
                        "status": "pending",
                        "sha256": file_state.sha256,
                        "size": file_state.size,
                        "modified_at": file_state.modified_at,
                        "document_id": whitelist_entry["document_id"],
                        "remote_name": whitelist_entry["remote_name"],
                        "indexing_status": whitelist_entry.get("indexing_status"),
                        "pipeline": pipeline,
                    }
                )
            else:
                whitelist[file_state.relative_path] = whitelist_entry
                record.update(
                    {
                        "status": "synced",
                        "sha256": file_state.sha256,
                        "size": file_state.size,
                        "modified_at": file_state.modified_at,
                        "document_id": whitelist_entry["document_id"],
                        "remote_name": whitelist_entry["remote_name"],
                        "indexing_status": whitelist_entry.get("indexing_status"),
                        "pipeline": pipeline,
                    }
                )
                if pipeline == "deepseek":
                    record["pipeline_version"] = PIPELINE_VERSION
        elif record.get("document_id"):
            record.pop("document_id", None)
            record.pop("remote_name", None)
            record.pop("indexing_status", None)
            record["status"] = "pending"
        file_records[file_state.relative_path] = record

    stale_keys = [key for key in file_records.keys() if key not in known_files]
    for key in stale_keys:
        file_records.pop(key, None)


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
                    "max_tokens": 1400,
                }
            },
        },
    }


STRUCTURAL_HEADING_RE = re.compile(
    r"^(?P<title>[一二三四五六七八九十]+[、.．]\s*.+|第[一二三四五六七八九十\d]+[章节节]\s*.+)$"
)


def promote_structural_headings(markdown: str) -> str:
    promoted: list[str] = []
    in_code = False
    for line in markdown.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        stripped = line.strip()
        if stripped.startswith("```"):
            in_code = not in_code
            promoted.append(line)
            continue
        if not in_code and STRUCTURAL_HEADING_RE.match(stripped) and not stripped.startswith("#"):
            promoted.append(f"## {stripped}")
            continue
        promoted.append(line)
    return "\n".join(promoted)


def enhance_markdown_for_retrieval(markdown: str, file_name: str) -> str:
    markdown = promote_structural_headings(markdown)
    markdown = add_retrieval_hints(markdown, file_name)
    return markdown.strip() + "\n"


def add_retrieval_hints(markdown: str, file_name: str) -> str:
    """Rewrite headings as semantic anchors without injecting visible metadata blocks."""
    document_name = Path(file_name).stem
    anchored: list[str] = []
    parent_title = document_name
    seen_titles: set[str] = set()
    in_code = False

    for line in markdown.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        stripped = line.strip()
        if stripped.startswith("```"):
            in_code = not in_code
            anchored.append(line)
            continue
        if in_code or not stripped.startswith("## "):
            anchored.append(line)
            continue

        title = stripped[3:].strip()
        if not title:
            anchored.append(line)
            continue
        if title.startswith(document_name):
            anchored_title = title
        else:
            anchored_title = f"{document_name} - {title}"
        if anchored_title in seen_titles:
            anchored.append(f"## {anchored_title}")
            continue
        seen_titles.add(anchored_title)
        parent_title = anchored_title
        anchored.append(f"## {anchored_title}")

    return "\n".join(anchored)

def normalize_body_for_similarity(text: str) -> str:
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
    body_lines: list[str] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        stripped = line.strip()
        if not stripped:
            if body_lines and body_lines[-1] != "":
                body_lines.append("")
            index += 1
            continue

        if "\t" in line:
            table_rows: list[list[str]] = []
            expected_cols = len(line.split("\t"))
            cursor = index
            while cursor < len(lines):
                candidate = lines[cursor]
                if not candidate.strip() or "\t" not in candidate:
                    break
                cells = [cell.strip() for cell in candidate.split("\t")]
                if len(cells) != expected_cols:
                    break
                table_rows.append(cells)
                cursor += 1
            if len(table_rows) >= 2 and expected_cols >= 2:
                body_lines.append("| " + " | ".join(table_rows[0]) + " |")
                body_lines.append("| " + " | ".join(["---"] * expected_cols) + " |")
                for row in table_rows[1:]:
                    body_lines.append("| " + " | ".join(row) + " |")
                index = cursor
                continue

        body_lines.append(line)
        index += 1

    body = "\n".join(body_lines).strip()
    if not body:
        return f"## {Path(file_name).stem}\n"
    if any(line.lstrip().startswith("#") for line in body_lines):
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


def iter_docx_blocks(document: DocxDocument):
    for child in document.element.body.iterchildren():
        if isinstance(child, CT_P):
            yield Paragraph(child, document)
        elif isinstance(child, CT_Tbl):
            yield Table(child, document)


def extract_docx_table_lines(table: Table) -> list[str]:
    lines: list[str] = []
    for row in table.rows:
        cells = [cell.text.strip() for cell in row.cells]
        if any(cells):
            lines.append("\t".join(cells))
    return lines


def extract_docx_text(path: Path) -> str:
    document = Document(path)
    lines: list[str] = []
    for block in iter_docx_blocks(document):
        if isinstance(block, Paragraph):
            text = block.text.strip()
            if text:
                lines.append(text)
            continue
        lines.extend(extract_docx_table_lines(block))
    return "\n".join(lines)


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


DEEPSEEK_SYSTEM_PROMPT = """你是一个顶尖的中文技术文档解析专家与 RAG（检索增强生成）知识库结构化专家。请将以下通过 OCR 或粗略提取的、排版混乱的源文本，重构成高质量、易于 RAG 精准检索的分段 Markdown 文档。

核心目标：
1. 最大化保真：100% 保留源文档中的技术细节。严禁润色、删减、归纳、压缩核心正文。
2. 语义孤岛化：利用稳定的章节边界（## 标题）确保后续知识库切片时，每个分段都是一个独立的、含义完整的知识点，避免上下文断裂。
3. 纯净输出：直接输出 Markdown 正文，严禁输出任何解释、总结、免责声明或代码围栏外的包裹性废话。

一、 文档类型自适应清洗规则
请先隐式判断输入文档的类型，并执行对应的清洗策略：
1. 实验报告/技术作业类：
   - 必须严格保留：实验目的、实验原理、具体步骤、测试数据、命令日志、实验结论。
   - 遇到数据表格、数值矩阵、代码输出结果时，必须精确对齐，严禁漏掉任何一个小数点、变量名或配置参数。
2. 实验模板/空白导向类：
   - 必须保留文档中的引导性文字、题目要求和评分标准。
   - 遇到形如 `[请在此处填写]`、`______` 或空白步骤框时，保留其结构占位符，不要将其作为噪声删掉。
3. 架构设计/技术规范类：
   - 侧重组件关系、协议流程（如 TCP 握手步骤）、环境配置项。保持逻辑链条的连续性。

二、 章节结构与 RAG 语义锚点注入（核心）
1. 统一二级标题切块：为了保证后续知识库按段落精准检索，允许将各个“子序号/子要点”（如“1.”、“2.”、“(一)”）升级为 Markdown 的二级标题 `## `。
2. 强制实施【父级锚点拼接】：任何子序号在升级为 `## ` 标题时，绝对不允许直接暴露孤立的子标题（如严禁出现单独的 `## 1. 交代科技背景`）。必须使用大板块的父级标题作为“语义锚点”向前进行前缀拼接。
   - 拼接公式：`## [父级大板块标题] - [子序号] [子标题内容]`
   - 黄金示例：
     若父级是：`## 一、引言段：引出“科技双刃剑”`
     子要是：`1. 交代科技背景`
     大模型必须将其重写并清洗为：`## 一、引言段：引出“科技双刃剑” - 1. 交代科技背景`
3. 多层嵌套传递：若存在多层嵌套，锚点需逐级向下传递（例如：`## 一、引言段 - 1. 交代背景 - (1) 具体行业案例`），确保每一个被切碎的小 Chunk 中都焊死带有最顶层的核心中文技术名词或分类词。
4. 头部处理：若文档开头存在无标题的总述，统一加上 `## 文档概述`。

三、 内容高保真格式化规范
1. 代码块与配置：
   - 所有代码（Java, Python, C, MATLAB, SQL等）、终端命令（Docker, SSH等）、配置内容（YAML, JSON等）必须严格使用 Markdown 代码围栏（```python ... ```）包裹，并明确指定语言类型。
   - 严禁拆散或折叠长代码逻辑。
2. 数据表格：
   - 粗略文本中的表格线条（如 +, -, | 乱序拼接）必须完全修复为标准的 Markdown 线性表格（| 标题 | 标题 |）。
   - 如果原表数据过于混乱无法对齐，请将其重构为 key-value 列表形式紧跟在对应的标题下方。
3. 噪声物理消除：
   - 必须剔除以下打印噪声：重复的页眉页脚、动态页码（如 "第 3 页 / 共 12 页"）、明显的评卷人签名栏、重复的水印占位符。
   - 注意：保留学生自填的实验心得、思考题解答，这些属于核心有效内容。

源文本内容如下，请开始进行结构化清洗："""


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
                        "content": f"请对以下源文本内容{chunk_note}进行结构化清洗：\n\n{raw_text}",
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
        candidates: list[UploadCandidate] = []
        for file_state in pending:
            if file_state.path.suffix.lower() in {".md", ".markdown", ".txt"}:
                raw_text = extract_source_text(file_state.path)
                output_path = markdown_output_path(file_state, archive_dir)
                markdown = enhance_markdown_for_retrieval(raw_text, output_path.name)
                output_path.parent.mkdir(parents=True, exist_ok=True)
                output_path.write_text(markdown, encoding="utf-8")
                candidates.append(
                    UploadCandidate(
                        source=file_state,
                        upload_path=output_path,
                        ledger_key=file_state.relative_path,
                        generated_relative_path=output_path.relative_to(archive_dir).as_posix(),
                    )
                )
                continue
            candidates.append(
                UploadCandidate(
                    source=file_state,
                    upload_path=file_state.path,
                    ledger_key=file_state.relative_path,
                )
            )
        return candidates

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
            markdown = enhance_markdown_for_retrieval(markdown, output_path.name)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(
                markdown,
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
    clear_remote: bool = False,
) -> SyncResult:
    files = iter_supported_files(source_dir)
    ledger = load_ledger(ledger_path)
    if dry_run:
        pending = [
            file_state for file_state in files if needs_upload(file_state, ledger, pipeline=pipeline)
        ]
        skipped = len(files) - len(pending)
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
    remote_documents = list_dataset_documents(
        base_url=base_url,
        dataset_api_key=dataset_api_key,
        dataset_id=dataset_id,
        session=active_session,
    )
    if clear_remote:
        deleted = clear_dataset_documents(
            base_url=base_url,
            dataset_api_key=dataset_api_key,
            dataset_id=dataset_id,
            remote_documents=remote_documents,
            session=active_session,
        )
        print(f"[CLEAR] deleted={deleted}")
        ledger = {"files": {}, "whitelist": {}}
        save_ledger(ledger_path, ledger)
        remote_documents = []
    refresh_ledger_whitelist(ledger, files, remote_documents, pipeline=pipeline)
    save_ledger(ledger_path, ledger)
    pending = [
        file_state for file_state in files if needs_upload(file_state, ledger, pipeline=pipeline)
    ]
    skipped = len(files) - len(pending)
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
    parser.add_argument(
        "--clear-remote",
        action="store_true",
        help="Delete all existing Dify dataset documents before uploading pending files.",
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
            clear_remote=args.clear_remote,
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
