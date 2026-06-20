#!/usr/bin/env python3
"""Evaluate Dify knowledge-base retrieval recall and precision.

The script is intentionally deterministic: it does not ask an LLM to judge
answers. Recall is measured by expected-term coverage in retrieved chunks.
Precision is measured by how many returned chunks are relevant to the expected
document or contain expected terms.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from dataclasses import asdict, dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse, urlunparse
from urllib.request import Request, urlopen


DEFAULT_CASES = [
    {
        "id": "architecture-bff",
        "query": "架构文档中的核心业务路由层指的是什么？",
        "expected_doc": "架构文档",
        "expected_terms": [
            "BFF",
            "Backend For Frontend",
            "业务网关层",
            "多模态文件智能鉴别引擎",
        ],
    },
    {
        "id": "wechat-send-file",
        "query": "微信通道中打开文件时应该怎么回传？",
        "expected_doc": "架构文档",
        "expected_terms": ["微信", "ClawBot", "send-file", "文件本体"],
    },
    {
        "id": "data-poisoning",
        "query": "第3讲 数据投毒攻击与防御中数据投毒是什么？",
        "expected_doc": "第3讲_数据投毒攻击与防御",
        "expected_terms": ["数据投毒", "攻击", "防御"],
    },
    {
        "id": "sync-quality",
        "query": "文件同步脚本如何保证清洗后的内容保真？",
        "expected_doc": "项目文档",
        "expected_terms": ["95%", "Markdown", "清洗", "Dify"],
    },
]


@dataclass
class RetrievedChunk:
    content: str
    document_name: str = ""
    score: float | None = None
    segment_id: str = ""


@dataclass
class CaseResult:
    case_id: str
    query: str
    expected_doc: str
    expected_terms: list[str]
    matched_terms: list[str]
    recall: float
    precision: float
    returned_count: int
    relevant_count: int
    mode: str
    chunks: list[dict[str, Any]]


def load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


def normalize_base_url(base_url: str) -> str:
    base = (base_url or "").strip().rstrip("/")
    if not base:
        return base
    return base if base.endswith("/v1") else f"{base}/v1"


def host_fallback_urls(base_url: str) -> list[str]:
    normalized = normalize_base_url(base_url)
    if not normalized:
        return []
    urls = [normalized]
    parsed = urlparse(normalized)
    if parsed.hostname in {"api", "dify-api", "dify_api"}:
        urls.append(urlunparse((parsed.scheme, "localhost", parsed.path, "", "", "")))
    return list(dict.fromkeys(urls))


def headers(api_key: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }




class HttpRequestError(Exception):
    pass


def request_json(
    method: str,
    url: str,
    *,
    api_key: str,
    timeout: int,
    params: dict[str, Any] | None = None,
    body: dict[str, Any] | None = None,
) -> tuple[int, dict[str, Any] | list[Any] | None, str]:
    if params:
        query = urlencode(params)
        separator = "&" if "?" in url else "?"
        url = f"{url}{separator}{query}"

    data = None
    request_headers = headers(api_key)
    if body is not None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")

    request = Request(url, data=data, headers=request_headers, method=method.upper())
    try:
        with urlopen(request, timeout=timeout) as response:
            text = response.read().decode("utf-8", errors="replace")
            try:
                payload: dict[str, Any] | list[Any] | None = json.loads(text) if text else None
            except json.JSONDecodeError:
                payload = None
            return int(response.status), payload, text
    except HTTPError as exc:
        text = exc.read().decode("utf-8", errors="replace")
        return int(exc.code), None, text
    except URLError as exc:
        raise HttpRequestError(str(exc.reason)) from exc
    except TimeoutError as exc:
        raise HttpRequestError("request timed out") from exc
def normalize_text(text: str) -> str:
    return re.sub(r"[\s\W_]+", "", text.lower(), flags=re.UNICODE)


def term_in_text(term: str, text: str) -> bool:
    term_norm = normalize_text(term)
    if not term_norm:
        return False
    return term_norm in normalize_text(text)


def short_snippet(text: str, limit: int = 220) -> str:
    compact = re.sub(r"\s+", " ", text).strip()
    return compact[:limit] + ("..." if len(compact) > limit else "")


def extract_chunks(payload: Any) -> list[RetrievedChunk]:
    records: Any
    if isinstance(payload, dict):
        records = payload.get("records") or payload.get("data") or payload.get("result") or []
    else:
        records = payload
    if isinstance(records, dict):
        records = records.get("records") or records.get("data") or records.get("result") or []
    if not isinstance(records, list):
        return []

    chunks: list[RetrievedChunk] = []
    for record in records:
        if not isinstance(record, dict):
            continue
        segment = record.get("segment") if isinstance(record.get("segment"), dict) else {}
        document = (
            segment.get("document")
            if isinstance(segment.get("document"), dict)
            else record.get("document")
            if isinstance(record.get("document"), dict)
            else {}
        )
        metadata = record.get("metadata") if isinstance(record.get("metadata"), dict) else {}
        content = (
            segment.get("content")
            or segment.get("text")
            or record.get("content")
            or record.get("text")
            or record.get("page_content")
            or ""
        )
        document_name = (
            document.get("name")
            or document.get("filename")
            or metadata.get("document_name")
            or metadata.get("source")
            or record.get("document_name")
            or record.get("source")
            or ""
        )
        score = record.get("score", segment.get("score"))
        try:
            score_value = float(score) if score is not None else None
        except (TypeError, ValueError):
            score_value = None
        chunks.append(
            RetrievedChunk(
                content=str(content),
                document_name=str(document_name),
                score=score_value,
                segment_id=str(segment.get("id") or record.get("segment_id") or record.get("id") or ""),
            )
        )
    return chunks


def retrieve_from_dify(
    *,
    base_urls: list[str],
    dataset_id: str,
    dataset_api_key: str,
    query: str,
    top_k: int,
    timeout: int,
) -> tuple[list[RetrievedChunk], str, str | None]:
    payloads = [
        {
            "query": query,
            "retrieval_model": {
                "search_method": "hybrid_search",
                "reranking_enable": True,
                "top_k": top_k,
                "score_threshold_enabled": False,
            },
        },
        {
            "query": query,
            "retrieval_model": {
                "search_method": "semantic_search",
                "top_k": top_k,
                "score_threshold_enabled": False,
            },
        },
        {"query": query},
    ]
    last_error: str | None = None
    for base_url in base_urls:
        url = f"{base_url}/datasets/{dataset_id}/retrieve"
        for payload in payloads:
            try:
                status_code, response_payload, response_text = request_json(
                    "POST",
                    url,
                    api_key=dataset_api_key,
                    body=payload,
                    timeout=timeout,
                )
            except HttpRequestError as exc:
                last_error = f"{base_url}: {exc}"
                continue
            if status_code >= 400:
                last_error = f"{base_url}: HTTP {status_code} {response_text[:300]}"
                continue
            chunks = extract_chunks(response_payload)
            if chunks:
                return chunks[:top_k], "dify", None
            last_error = f"{base_url}: empty retrieve result"
    return [], "dify", last_error


def list_dataset_documents(base_urls: list[str], dataset_id: str, dataset_api_key: str, timeout: int) -> tuple[list[dict[str, Any]], str | None]:
    last_error: str | None = None
    for base_url in base_urls:
        docs: list[dict[str, Any]] = []
        page = 1
        while True:
            url = f"{base_url}/datasets/{dataset_id}/documents"
            try:
                status_code, payload, response_text = request_json(
                    "GET",
                    url,
                    api_key=dataset_api_key,
                    params={"page": page, "limit": 100},
                    timeout=timeout,
                )
            except HttpRequestError as exc:
                last_error = f"{base_url}: {exc}"
                break
            if status_code >= 400:
                last_error = f"{base_url}: HTTP {status_code} {response_text[:300]}"
                break
            data = payload.get("data") if isinstance(payload, dict) else payload
            if not isinstance(data, list):
                last_error = f"{base_url}: unexpected documents payload"
                break
            docs.extend(data)
            if not isinstance(payload, dict) or not payload.get("has_more"):
                return docs, None
            page += 1
        if docs:
            return docs, None
    return [], last_error


def list_document_segments(
    base_urls: list[str],
    dataset_id: str,
    document_id: str,
    dataset_api_key: str,
    timeout: int,
) -> tuple[list[dict[str, Any]], str | None]:
    last_error: str | None = None
    for base_url in base_urls:
        segments: list[dict[str, Any]] = []
        page = 1
        while True:
            url = f"{base_url}/datasets/{dataset_id}/documents/{document_id}/segments"
            try:
                status_code, payload, response_text = request_json(
                    "GET",
                    url,
                    api_key=dataset_api_key,
                    params={"page": page, "limit": 100},
                    timeout=timeout,
                )
            except HttpRequestError as exc:
                last_error = f"{base_url}: {exc}"
                break
            if status_code >= 400:
                last_error = f"{base_url}: HTTP {status_code} {response_text[:300]}"
                break
            data = payload.get("data") if isinstance(payload, dict) else payload
            if not isinstance(data, list):
                last_error = f"{base_url}: unexpected segments payload"
                break
            segments.extend(data)
            if not isinstance(payload, dict) or not payload.get("has_more"):
                return segments, None
            page += 1
        if segments:
            return segments, None
    return [], last_error


def local_retrieve_segments(
    *,
    base_urls: list[str],
    dataset_id: str,
    dataset_api_key: str,
    query: str,
    top_k: int,
    timeout: int,
) -> tuple[list[RetrievedChunk], str | None]:
    documents, error = list_dataset_documents(base_urls, dataset_id, dataset_api_key, timeout)
    if not documents:
        return [], error or "no dataset documents"

    all_chunks: list[RetrievedChunk] = []
    for document in documents:
        document_id = str(document.get("id") or "")
        if not document_id:
            continue
        name = str(document.get("name") or document.get("display_name") or document.get("filename") or "")
        segments, _ = list_document_segments(base_urls, dataset_id, document_id, dataset_api_key, timeout)
        for segment in segments:
            if not isinstance(segment, dict):
                continue
            content = str(segment.get("content") or segment.get("text") or "")
            if not content.strip():
                continue
            score = lexical_score(query, f"{name}\n{content}")
            all_chunks.append(
                RetrievedChunk(
                    content=content,
                    document_name=name,
                    score=score,
                    segment_id=str(segment.get("id") or ""),
                )
            )
    all_chunks.sort(key=lambda item: item.score or 0, reverse=True)
    return all_chunks[:top_k], None


def lexical_score(query: str, text: str) -> float:
    query_norm = normalize_text(query)
    text_norm = normalize_text(text)
    if not query_norm or not text_norm:
        return 0.0

    query_terms = [term for term in re.split(r"[\s，。！？、：:；;（）()\[\]【】\"'“”‘’/\\_-]+", query) if len(term.strip()) >= 2]
    hit_bonus = sum(1 for term in query_terms if term_in_text(term, text)) / max(len(query_terms), 1)
    ratio = SequenceMatcher(None, query_norm[:120], text_norm[:4000]).ratio()
    substring_bonus = 1.0 if query_norm in text_norm else 0.0
    return min(1.0, ratio * 0.35 + hit_bonus * 0.55 + substring_bonus * 0.10)


def evaluate_case(case: dict[str, Any], chunks: list[RetrievedChunk], mode: str) -> CaseResult:
    expected_terms = [str(term) for term in case.get("expected_terms", []) if str(term).strip()]
    expected_doc = str(case.get("expected_doc") or "").strip()
    combined_text = "\n".join([chunk.document_name + "\n" + chunk.content for chunk in chunks])
    matched_terms = [term for term in expected_terms if term_in_text(term, combined_text)]
    recall = len(matched_terms) / len(expected_terms) if expected_terms else 0.0

    relevant_count = 0
    for chunk in chunks:
        doc_match = bool(expected_doc and term_in_text(expected_doc, chunk.document_name))
        term_match = any(term_in_text(term, chunk.content) for term in expected_terms)
        if doc_match or term_match:
            relevant_count += 1
    precision = relevant_count / len(chunks) if chunks else 0.0

    return CaseResult(
        case_id=str(case.get("id") or case.get("query") or "case"),
        query=str(case.get("query") or ""),
        expected_doc=expected_doc,
        expected_terms=expected_terms,
        matched_terms=matched_terms,
        recall=recall,
        precision=precision,
        returned_count=len(chunks),
        relevant_count=relevant_count,
        mode=mode,
        chunks=[
            {
                "document_name": chunk.document_name,
                "score": chunk.score,
                "segment_id": chunk.segment_id,
                "snippet": short_snippet(chunk.content),
            }
            for chunk in chunks
        ],
    )


def load_cases(path: Path | None) -> list[dict[str, Any]]:
    if path is None:
        return DEFAULT_CASES
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if isinstance(payload, dict):
        payload = payload.get("cases")
    if not isinstance(payload, list):
        raise ValueError("cases file must be a JSON list or an object with a 'cases' list")
    return payload


def print_template() -> None:
    print(json.dumps({"cases": DEFAULT_CASES}, ensure_ascii=False, indent=2))


def format_percent(value: float) -> str:
    return f"{value * 100:.1f}%"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate Dify knowledge-base retrieval recall and precision.")
    parser.add_argument("--cases", type=Path, help="JSON benchmark cases file. Defaults to built-in sample cases.")
    parser.add_argument("--base-url", default=os.getenv("DIFY_BASE_URL", ""), help="Dify base URL. Defaults to DIFY_BASE_URL.")
    parser.add_argument("--dataset-api-key", default=os.getenv("DIFY_DATASET_API_KEY", ""), help="Dify Dataset API key.")
    parser.add_argument("--dataset-id", default=os.getenv("DIFY_DATASET_ID", ""), help="Dify Dataset ID.")
    parser.add_argument("--top-k", type=int, default=10, help="Number of chunks to retrieve per query.")
    parser.add_argument("--threshold", type=float, default=0.80, help="Pass threshold for recall and precision.")
    parser.add_argument("--timeout", type=int, default=30, help="HTTP timeout seconds.")
    parser.add_argument("--mode", choices=["auto", "dify", "local"], default="auto", help="auto/dify call Dify retrieve API; local fetches Dataset segments and uses deterministic lexical scoring.")
    parser.add_argument("--output", type=Path, help="Optional JSON report path.")
    parser.add_argument("--fail-under-threshold", action="store_true", help="Exit with code 1 if any case is below threshold.")
    parser.add_argument("--list-template", action="store_true", help="Print an editable benchmark JSON template and exit.")
    return parser.parse_args()


def main() -> int:
    load_dotenv(Path(".env"))
    args = parse_args()

    if args.list_template:
        print_template()
        return 0

    missing = []
    if not args.base_url:
        missing.append("DIFY_BASE_URL")
    if not args.dataset_api_key:
        missing.append("DIFY_DATASET_API_KEY")
    if not args.dataset_id:
        missing.append("DIFY_DATASET_ID")
    if missing:
        print(f"缺少配置：{', '.join(missing)}。请写入 .env 或通过命令行参数传入。", file=sys.stderr)
        return 2

    cases = load_cases(args.cases)
    base_urls = host_fallback_urls(args.base_url)
    print(f"知识库检索评估开始：cases={len(cases)}, top_k={args.top_k}, threshold={format_percent(args.threshold)}")
    print(f"Dify URL 候选：{', '.join(base_urls)}")

    results: list[CaseResult] = []
    errors: list[str] = []
    started = time.time()

    for case in cases:
        query = str(case.get("query") or "")
        if not query:
            errors.append(f"{case.get('id', '<unknown>')}: empty query")
            continue

        chunks: list[RetrievedChunk] = []
        mode_used = args.mode
        if args.mode in {"auto", "dify"}:
            chunks, mode_used, error = retrieve_from_dify(
                base_urls=base_urls,
                dataset_id=args.dataset_id,
                dataset_api_key=args.dataset_api_key,
                query=query,
                top_k=args.top_k,
                timeout=args.timeout,
            )
            if error and args.mode in {"auto", "dify"}:
                errors.append(f"{case.get('id', query)}: {error}")
        if args.mode == "local":
            local_chunks, error = local_retrieve_segments(
                base_urls=base_urls,
                dataset_id=args.dataset_id,
                dataset_api_key=args.dataset_api_key,
                query=query,
                top_k=args.top_k,
                timeout=args.timeout,
            )
            if local_chunks:
                chunks = local_chunks
                mode_used = "local"
            elif error:
                errors.append(f"{case.get('id', query)}: {error}")

        result = evaluate_case(case, chunks, mode_used)
        results.append(result)
        status = "PASS" if result.recall >= args.threshold and result.precision >= args.threshold else "FAIL"
        print(
            f"[{status}] {result.case_id} | "
            f"Recall={format_percent(result.recall)} ({len(result.matched_terms)}/{len(result.expected_terms)}) | "
            f"Precision={format_percent(result.precision)} ({result.relevant_count}/{result.returned_count}) | "
            f"mode={result.mode}"
        )

    macro_recall = sum(item.recall for item in results) / len(results) if results else 0.0
    macro_precision = sum(item.precision for item in results) / len(results) if results else 0.0
    bad_cases = [item for item in results if item.recall < args.threshold or item.precision < args.threshold]

    print("\n总体结果")
    print(f"- Macro Recall: {format_percent(macro_recall)}")
    print(f"- Macro Precision: {format_percent(macro_precision)}")
    print(f"- Bad Cases: {len(bad_cases)}")
    print(f"- Elapsed: {time.time() - started:.1f}s")

    if bad_cases:
        print("\nBad Case 明细")
        for item in bad_cases:
            missing_terms = [term for term in item.expected_terms if term not in item.matched_terms]
            print(f"\n[{item.case_id}] {item.query}")
            print(f"  expected_doc: {item.expected_doc}")
            print(f"  matched_terms: {item.matched_terms}")
            print(f"  missing_terms: {missing_terms}")
            print(f"  top_chunks:")
            for idx, chunk in enumerate(item.chunks[:5], start=1):
                print(f"    {idx}. doc={chunk['document_name']} score={chunk['score']} snippet={chunk['snippet']}")

    if errors:
        print("\n接口/配置错误")
        for error in errors:
            print(f"- {error}")

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        report = {
            "macro_recall": macro_recall,
            "macro_precision": macro_precision,
            "threshold": args.threshold,
            "top_k": args.top_k,
            "results": [asdict(item) for item in results],
            "errors": errors,
        }
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\nJSON 报告已写入：{args.output}")

    if args.fail_under_threshold and bad_cases:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
