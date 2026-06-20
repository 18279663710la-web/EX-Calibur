#!/usr/bin/env python3
"""Build and run a 20-case RAG retrieval evaluation through Dify Chatflow.

Dataset APIs are used only to inspect the current knowledge-base documents and
create ground-truth cases from existing segments. The actual evaluation calls
the Dify Chatflow `/chat-messages` endpoint, then scores the chunks surfaced by
the workflow.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse, urlunparse
from urllib.request import Request, urlopen


STOP_TERMS = {
    "来源文件",
    "文档名称",
    "章节标题",
    "检索关键词",
    "模块",
    "文件",
    "文档",
    "内容",
    "部分",
    "说明",
}


@dataclass
class Document:
    id: str
    name: str
    status: str


@dataclass
class Segment:
    document_id: str
    document_name: str
    segment_id: str
    content: str


@dataclass
class EvalCase:
    case_id: str
    query: str
    expected_doc: str
    expected_terms: list[str]
    source_segment_id: str
    source_snippet: str


@dataclass
class ChatflowResult:
    answer: str
    chunks: list[dict[str, Any]]
    raw_events: int
    error: str = ""


def load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def normalize_base_url(base_url: str) -> str:
    base = (base_url or "").strip().rstrip("/")
    if not base:
        return base
    return base if base.endswith("/v1") else f"{base}/v1"


def candidate_base_urls(base_url: str) -> list[str]:
    normalized = normalize_base_url(base_url)
    urls = [normalized] if normalized else []
    parsed = urlparse(normalized)
    if parsed.hostname in {"api", "dify-api", "dify_api"}:
        urls.append(urlunparse((parsed.scheme, "localhost", parsed.path, "", "", "")))
    return list(dict.fromkeys(urls))


def request_json(
    method: str,
    url: str,
    *,
    api_key: str,
    timeout: int,
    params: dict[str, Any] | None = None,
    body: dict[str, Any] | None = None,
) -> tuple[int, Any, str]:
    if params:
        url = f"{url}?{urlencode(params)}"
    data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
    request = Request(
        url,
        data=data,
        method=method.upper(),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            text = response.read().decode("utf-8", errors="replace")
            return int(response.status), json.loads(text) if text else None, text
    except HTTPError as exc:
        text = exc.read().decode("utf-8", errors="replace")
        return int(exc.code), None, text
    except (URLError, TimeoutError) as exc:
        return 0, None, str(exc)


def list_documents(base_urls: list[str], dataset_id: str, dataset_key: str, timeout: int) -> tuple[list[Document], str]:
    last_error = ""
    for base_url in base_urls:
        docs: list[Document] = []
        page = 1
        while True:
            status, payload, text = request_json(
                "GET",
                f"{base_url}/datasets/{dataset_id}/documents",
                api_key=dataset_key,
                params={"page": page, "limit": 100},
                timeout=timeout,
            )
            if status != 200 or not isinstance(payload, dict):
                last_error = f"{base_url}: HTTP {status} {text[:240]}"
                break
            data = payload.get("data")
            if not isinstance(data, list):
                last_error = f"{base_url}: unexpected documents payload"
                break
            for item in data:
                if not isinstance(item, dict):
                    continue
                docs.append(
                    Document(
                        id=str(item.get("id") or ""),
                        name=str(item.get("name") or item.get("display_name") or item.get("filename") or ""),
                        status=str(item.get("indexing_status") or item.get("status") or ""),
                    )
                )
            if not payload.get("has_more"):
                return docs, ""
            page += 1
    return [], last_error


def list_segments(
    base_urls: list[str],
    dataset_id: str,
    dataset_key: str,
    document: Document,
    timeout: int,
    max_segments: int,
) -> list[Segment]:
    for base_url in base_urls:
        segments: list[Segment] = []
        page = 1
        while len(segments) < max_segments:
            status, payload, _ = request_json(
                "GET",
                f"{base_url}/datasets/{dataset_id}/documents/{document.id}/segments",
                api_key=dataset_key,
                params={"page": page, "limit": 100},
                timeout=timeout,
            )
            if status != 200 or not isinstance(payload, dict):
                break
            data = payload.get("data")
            if not isinstance(data, list):
                break
            for item in data:
                if not isinstance(item, dict):
                    continue
                content = str(item.get("content") or item.get("text") or "").strip()
                if len(content) < 80:
                    continue
                segments.append(
                    Segment(
                        document_id=document.id,
                        document_name=document.name,
                        segment_id=str(item.get("id") or ""),
                        content=content,
                    )
                )
            if not payload.get("has_more"):
                return segments[:max_segments]
            page += 1
        if segments:
            return segments[:max_segments]
    return []


def clean_doc_name(name: str) -> str:
    return re.sub(r"\.(md|pdf|docx|txt|pptx|xlsx)$", "", name, flags=re.I)


def first_heading(content: str) -> str:
    for line in content.splitlines():
        stripped = line.strip(" #\t")
        if not stripped:
            continue
        if stripped.startswith(("来源文件", "文档名称", "检索关键词")):
            continue
        return stripped[:80]
    return "核心内容"


def extract_terms(content: str, doc_name: str, limit: int = 5) -> list[str]:
    candidates: list[str] = []
    heading = first_heading(content)
    for value in [heading, clean_doc_name(doc_name)]:
        value = value.strip()
        if value and value not in candidates:
            candidates.append(value)

    tokens = re.findall(r"[A-Za-z][A-Za-z0-9_+/#.-]{2,}|[\u4e00-\u9fff]{2,12}|\d+(?:\.\d+)?%?", content)
    seen = {normalize_text(item) for item in candidates}
    for token in tokens:
        token = token.strip()
        norm = normalize_text(token)
        if not norm or norm in seen or token in STOP_TERMS:
            continue
        if len(token) < 2:
            continue
        candidates.append(token)
        seen.add(norm)
        if len(candidates) >= limit:
            break
    return candidates[:limit]


def build_cases(segments: list[Segment], limit: int) -> list[EvalCase]:
    cases: list[EvalCase] = []
    used_docs: dict[str, int] = {}
    sorted_segments = sorted(segments, key=lambda seg: (used_docs.get(seg.document_name, 0), seg.document_name, seg.segment_id))
    templates = [
        "请根据《{doc}》说明“{topic}”这一部分的核心内容。",
        "《{doc}》中关于“{topic}”是怎么描述的？",
        "帮我找一下《{doc}》里的“{topic}”部分内容。",
        "《{doc}》的“{topic}”包含哪些关键信息？",
    ]
    for segment in sorted_segments:
        if len(cases) >= limit:
            break
        doc_key = clean_doc_name(segment.document_name)
        topic = first_heading(segment.content)
        terms = extract_terms(segment.content, segment.document_name)
        if len(terms) < 3:
            continue
        index = len(cases)
        query = templates[index % len(templates)].format(doc=doc_key, topic=topic)
        used_docs[segment.document_name] = used_docs.get(segment.document_name, 0) + 1
        cases.append(
            EvalCase(
                case_id=f"case-{index + 1:02d}",
                query=query,
                expected_doc=segment.document_name,
                expected_terms=terms,
                source_segment_id=segment.segment_id,
                source_snippet=short_snippet(segment.content, 260),
            )
        )
    return cases


def stream_chatflow(base_urls: list[str], app_key: str, query: str, timeout: int, user: str) -> ChatflowResult:
    bodies = [
        {
            "inputs": {"userinput": {"query": query, "files": []}},
            "query": query,
            "response_mode": "streaming",
            "user": user,
        },
        {
            "inputs": {},
            "query": query,
            "response_mode": "streaming",
            "user": user,
        },
    ]
    last_error = ""
    for base_url in base_urls:
        url = f"{base_url}/chat-messages"
        for body in bodies:
            request = Request(
                url,
                data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
                method="POST",
                headers={
                    "Authorization": f"Bearer {app_key}",
                    "Content-Type": "application/json",
                },
            )
            try:
                with urlopen(request, timeout=timeout) as response:
                    return parse_sse(response.read().decode("utf-8", errors="replace"))
            except HTTPError as exc:
                last_error = f"{base_url}: HTTP {exc.code} {exc.read().decode('utf-8', errors='replace')[:240]}"
                continue
            except (URLError, TimeoutError) as exc:
                last_error = f"{base_url}: {exc}"
                break
    return ChatflowResult(answer="", chunks=[], raw_events=0, error=last_error or "chatflow request failed")


def parse_sse(text: str) -> ChatflowResult:
    answer_parts: list[str] = []
    chunks: list[dict[str, Any]] = []
    event_count = 0
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("data:"):
            continue
        event_count += 1
        raw = line[5:].strip()
        if not raw or raw == "[DONE]":
            continue
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            continue
        answer_parts.append(extract_answer_token(data))
        chunks.extend(extract_retrieval_chunks(data))
    answer = "".join(part for part in answer_parts if part)
    deduped: list[dict[str, Any]] = []
    seen = set()
    for chunk in chunks:
        key = (chunk.get("document_name"), chunk.get("content", "")[:120])
        if key in seen:
            continue
        seen.add(key)
        deduped.append(chunk)
    return ChatflowResult(answer=answer, chunks=deduped, raw_events=event_count)


def extract_answer_token(data: dict[str, Any]) -> str:
    event = data.get("event")
    payload = data.get("data") if isinstance(data.get("data"), dict) else {}
    if event == "text_chunk":
        return str(payload.get("text") or "")
    if event in {"message", "agent_message"}:
        return str(data.get("answer") or payload.get("answer") or "")
    return ""


def extract_retrieval_chunks(data: dict[str, Any]) -> list[dict[str, Any]]:
    chunks: list[dict[str, Any]] = []
    payload = data.get("data") if isinstance(data.get("data"), dict) else {}

    if payload.get("node_type") == "knowledge-retrieval":
        outputs = payload.get("outputs") if isinstance(payload.get("outputs"), dict) else {}
        results = outputs.get("result")
        if isinstance(results, list):
            chunks.extend(chunk_from_records(results))

    metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else data.get("metadata")
    if isinstance(metadata, dict):
        resources = metadata.get("retriever_resources")
        if isinstance(resources, list):
            chunks.extend(chunk_from_records(resources))
    return chunks


def chunk_from_records(records: list[Any]) -> list[dict[str, Any]]:
    chunks: list[dict[str, Any]] = []
    for record in records:
        if not isinstance(record, dict):
            continue
        segment = record.get("segment") if isinstance(record.get("segment"), dict) else {}
        metadata = record.get("metadata") if isinstance(record.get("metadata"), dict) else {}
        document = segment.get("document") if isinstance(segment.get("document"), dict) else {}
        content = str(record.get("content") or record.get("text") or segment.get("content") or segment.get("text") or "")
        document_name = str(
            metadata.get("document_name")
            or metadata.get("source")
            or record.get("document_name")
            or document.get("name")
            or ""
        )
        score = record.get("score") or segment.get("score")
        chunks.append(
            {
                "document_name": document_name,
                "score": score,
                "content": content,
                "snippet": short_snippet(content, 220),
            }
        )
    return chunks


def normalize_text(text: str) -> str:
    return re.sub(r"[\s\W_]+", "", text.lower(), flags=re.UNICODE)


def term_in_text(term: str, text: str) -> bool:
    norm = normalize_text(term)
    return bool(norm and norm in normalize_text(text))


def short_snippet(text: str, limit: int = 180) -> str:
    compact = re.sub(r"\s+", " ", text).strip()
    return compact[:limit] + ("..." if len(compact) > limit else "")


def score_case(case: EvalCase, result: ChatflowResult) -> dict[str, Any]:
    combined_chunks = "\n".join(str(chunk.get("document_name", "")) + "\n" + str(chunk.get("content", "")) for chunk in result.chunks)
    combined_answer = result.answer
    matched_terms = [term for term in case.expected_terms if term_in_text(term, combined_chunks)]
    answer_terms = [term for term in case.expected_terms if term_in_text(term, combined_answer)]
    recall = len(matched_terms) / len(case.expected_terms) if case.expected_terms else 0.0
    answer_recall = len(answer_terms) / len(case.expected_terms) if case.expected_terms else 0.0
    relevant_count = 0
    for chunk in result.chunks:
        doc_match = term_in_text(clean_doc_name(case.expected_doc), str(chunk.get("document_name", "")))
        term_match = any(term_in_text(term, str(chunk.get("content", ""))) for term in case.expected_terms)
        if doc_match or term_match:
            relevant_count += 1
    precision = relevant_count / len(result.chunks) if result.chunks else 0.0
    return {
        "matched_terms": matched_terms,
        "answer_terms": answer_terms,
        "missing_terms": [term for term in case.expected_terms if term not in matched_terms],
        "recall": recall,
        "precision": precision,
        "answer_recall": answer_recall,
        "relevant_count": relevant_count,
        "returned_count": len(result.chunks),
    }


def percent(value: float) -> str:
    return f"{value * 100:.1f}%"


def write_report(
    path: Path,
    *,
    documents: list[Document],
    cases: list[EvalCase],
    rows: list[dict[str, Any]],
    threshold: float,
) -> None:
    macro_recall = sum(row["score"]["recall"] for row in rows) / len(rows) if rows else 0.0
    macro_precision = sum(row["score"]["precision"] for row in rows) / len(rows) if rows else 0.0
    macro_answer_recall = sum(row["score"]["answer_recall"] for row in rows) / len(rows) if rows else 0.0
    bad_rows = [row for row in rows if row["score"]["recall"] < threshold or row["score"]["precision"] < threshold]

    lines: list[str] = []
    lines.append("# CloudRAG Dify Chatflow 知识库召回测试结果")
    lines.append("")
    lines.append(f"- 测试时间：{time.strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append("- 评测方式：先读取 Dify Dataset 文档与分段生成问题；实际测试阶段仅调用 Dify Chatflow `/chat-messages`。")
    lines.append(f"- 用例数量：{len(cases)}")
    lines.append(f"- 通过阈值：Recall >= {percent(threshold)}，Precision >= {percent(threshold)}")
    lines.append(f"- Macro Recall：{percent(macro_recall)}")
    lines.append(f"- Macro Precision：{percent(macro_precision)}")
    lines.append(f"- Macro Answer Term Coverage：{percent(macro_answer_recall)}")
    lines.append(f"- Bad Case 数量：{len(bad_rows)}")
    lines.append("")

    lines.append("## 当前 Dify 知识库文档")
    lines.append("")
    lines.append("| 序号 | 文档名 | 索引状态 |")
    lines.append("|---:|---|---|")
    for index, document in enumerate(documents, start=1):
        lines.append(f"| {index} | {document.name} | {document.status} |")
    lines.append("")

    lines.append("## 汇总表")
    lines.append("")
    lines.append("| ID | 问题 | 预期文档 | Recall | Precision | Answer覆盖 | 返回Chunk | 状态 |")
    lines.append("|---|---|---|---:|---:|---:|---:|---|")
    for row in rows:
        case = row["case"]
        score = row["score"]
        status = "PASS" if score["recall"] >= threshold and score["precision"] >= threshold else "FAIL"
        lines.append(
            f"| {case.case_id} | {case.query} | {case.expected_doc} | "
            f"{percent(score['recall'])} | {percent(score['precision'])} | {percent(score['answer_recall'])} | "
            f"{score['returned_count']} | {status} |"
        )
    lines.append("")

    lines.append("## Bad Case 明细")
    lines.append("")
    if not bad_rows:
        lines.append("无。")
    for row in bad_rows:
        case = row["case"]
        result = row["result"]
        score = row["score"]
        lines.append(f"### {case.case_id}：{case.query}")
        lines.append("")
        lines.append(f"- 预期文档：{case.expected_doc}")
        lines.append(f"- 预期关键词：{', '.join(case.expected_terms)}")
        lines.append(f"- 命中关键词：{', '.join(score['matched_terms']) if score['matched_terms'] else '无'}")
        lines.append(f"- 缺失关键词：{', '.join(score['missing_terms']) if score['missing_terms'] else '无'}")
        lines.append(f"- Recall / Precision：{percent(score['recall'])} / {percent(score['precision'])}")
        if result.error:
            lines.append(f"- Chatflow 错误：{result.error}")
        lines.append(f"- 答案摘要：{short_snippet(result.answer, 320) if result.answer else '无'}")
        lines.append("- 返回 Chunk：")
        if not result.chunks:
            lines.append("  - 无")
        for idx, chunk in enumerate(result.chunks[:5], start=1):
            lines.append(f"  - {idx}. `{chunk.get('document_name')}` score={chunk.get('score')}：{chunk.get('snippet')}")
        lines.append("")

    lines.append("## 20 条测试问题与 Ground Truth")
    lines.append("")
    for case in cases:
        lines.append(f"### {case.case_id}")
        lines.append("")
        lines.append(f"- Query：{case.query}")
        lines.append(f"- Expected Doc：{case.expected_doc}")
        lines.append(f"- Expected Terms：{', '.join(case.expected_terms)}")
        lines.append(f"- Source Segment：{case.source_segment_id}")
        lines.append(f"- Source Snippet：{case.source_snippet}")
        lines.append("")

    path.write_text("\n".join(lines), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate Dify Chatflow RAG recall/precision with auto-generated cases.")
    parser.add_argument("--base-url", default=os.getenv("DIFY_BASE_URL", ""))
    parser.add_argument("--dataset-api-key", default=os.getenv("DIFY_DATASET_API_KEY", ""))
    parser.add_argument("--dataset-id", default=os.getenv("DIFY_DATASET_ID", ""))
    parser.add_argument("--app-api-key", default=os.getenv("DIFY_API_KEY", ""))
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--threshold", type=float, default=0.80)
    parser.add_argument("--timeout", type=int, default=120)
    parser.add_argument("--output", type=Path, default=Path("测试结果.md"))
    parser.add_argument("--cases-json", type=Path, default=Path("reports/chatflow_retrieval_cases.json"))
    return parser.parse_args()


def main() -> int:
    load_dotenv(Path(".env"))
    args = parse_args()
    missing = [
        name
        for name, value in {
            "DIFY_BASE_URL": args.base_url,
            "DIFY_DATASET_API_KEY": args.dataset_api_key,
            "DIFY_DATASET_ID": args.dataset_id,
            "DIFY_API_KEY": args.app_api_key,
        }.items()
        if not value
    ]
    if missing:
        print(f"缺少配置：{', '.join(missing)}", file=sys.stderr)
        return 2

    base_urls = candidate_base_urls(args.base_url)
    print(f"读取 Dify 知识库文档：{', '.join(base_urls)}")
    documents, error = list_documents(base_urls, args.dataset_id, args.dataset_api_key, args.timeout)
    if not documents:
        print(f"无法读取知识库文档：{error}", file=sys.stderr)
        return 1
    print(f"当前知识库文档数：{len(documents)}")
    for index, document in enumerate(documents, start=1):
        print(f"{index:02d}. {document.name} [{document.status}]")

    all_segments: list[Segment] = []
    for document in documents:
        all_segments.extend(list_segments(base_urls, args.dataset_id, args.dataset_api_key, document, args.timeout, max_segments=5))
    cases = build_cases(all_segments, args.limit)
    if len(cases) < args.limit:
        print(f"可用分段不足，只生成 {len(cases)} 条用例。")

    args.cases_json.parent.mkdir(parents=True, exist_ok=True)
    args.cases_json.write_text(
        json.dumps([case.__dict__ for case in cases], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"已生成测试问题：{args.cases_json}")

    rows: list[dict[str, Any]] = []
    for index, case in enumerate(cases, start=1):
        print(f"[{index}/{len(cases)}] {case.query}")
        result = stream_chatflow(base_urls, args.app_api_key, case.query, args.timeout, user=f"cloudrag-rag-eval-{index}")
        score = score_case(case, result)
        rows.append({"case": case, "result": result, "score": score})
        print(
            f"  Recall={percent(score['recall'])}, Precision={percent(score['precision'])}, "
            f"Answer={percent(score['answer_recall'])}, chunks={score['returned_count']}"
        )

    write_report(args.output, documents=documents, cases=cases, rows=rows, threshold=args.threshold)
    print(f"测试报告已生成：{args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
