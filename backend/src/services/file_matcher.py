from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from rapidfuzz import fuzz


MATCH_THRESHOLD = 70
DEFAULT_TOP_K = 5


def iter_knowledge_files(knowledge_dir: str | Path) -> list[Path]:
    root = Path(knowledge_dir).resolve()
    if not root.exists():
        return []
    files: list[Path] = []
    for current_root, _, names in os.walk(root):
        for name in names:
            if _should_skip_file(name):
                continue
            files.append(Path(current_root) / name)
    return files


def requested_basename(filename: str) -> str:
    return Path(str(filename or "").replace("\\", "/")).name


def normalize_query(text: str) -> str:
    value = str(text or "").strip()
    if not value:
        return ""
    for prefix in ("打开", "查看", "预览", "发送", "回传"):
        if value.startswith(prefix):
            value = value[len(prefix):].strip()
            break
    for token in (
        "请",
        "帮我",
        "把",
        "完整的",
        "完整",
        "文档",
        "文件",
        "给我",
        "发我",
        "传给我",
        "打开",
        "查看",
        "预览",
        "发送",
        "回传",
        "一下",
        "这个",
        "那个",
    ):
        value = value.replace(token, " ")
    punctuation_chars = "\"'`,.:;!?()[]{}<>"
    for ch in punctuation_chars:
        value = value.replace(ch, " ")
    return " ".join(value.split())


def match_score(query: str, filename: str) -> float:
    normalized_query = _compact_text(normalize_query(query))
    normalized_filename = _compact_text(Path(str(filename or "")).stem)
    if not normalized_query or not normalized_filename:
        return 0
    fuzzy_score = float(fuzz.partial_ratio(normalized_query, normalized_filename))
    coverage_score = _ordered_subsequence_ratio(normalized_query, normalized_filename)
    return max(fuzzy_score, coverage_score)


def search_knowledge_files(
    query: str,
    *,
    knowledge_dir: str | Path,
    top_k: int = DEFAULT_TOP_K,
    threshold: float = MATCH_THRESHOLD,
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for path in iter_knowledge_files(knowledge_dir):
        score = match_score(query, path.name)
        if score < threshold:
            continue
        results.append(
            {
                "file_name": path.name,
                "filename": path.name,
                "path": str(path),
                "score": score,
                "size_bytes": path.stat().st_size,
            }
        )
    results.sort(key=lambda item: (-float(item["score"]), str(item["file_name"]).lower()))
    return results[:top_k]


def resolve_best_match(
    query: str,
    *,
    knowledge_dir: str | Path,
    threshold: float = MATCH_THRESHOLD,
) -> Path | None:
    requested = requested_basename(query)
    if not requested:
        return None

    files = iter_knowledge_files(knowledge_dir)
    for path in files:
        if path.name == requested:
            return path

    requested_lower = requested.lower()
    for path in files:
        if path.name.lower() == requested_lower:
            return path

    matches = search_knowledge_files(
        requested,
        knowledge_dir=knowledge_dir,
        top_k=1,
        threshold=threshold,
    )
    if not matches:
        return None
    return Path(matches[0]["path"])


def _compact_text(value: str) -> str:
    return "".join(
        ch for ch in str(value or "").lower()
        if ch.isdigit() or ("a" <= ch <= "z") or ("\u4e00" <= ch <= "\u9fff")
    )


def _ordered_subsequence_ratio(query: str, target: str) -> float:
    if not query or not target:
        return 0
    index = 0
    for ch in target:
        if index < len(query) and ch == query[index]:
            index += 1
    return index / len(query) * 100


def _should_skip_file(name: str) -> bool:
    value = str(name or "")
    return value.startswith("~$")
