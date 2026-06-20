#!/usr/bin/env python3
"""Run 30 manual Ground Truth cases through Dify Chatflow and combine with baseline."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

from evaluate_chatflow_rag import (
    ChatflowResult,
    Document,
    EvalCase,
    candidate_base_urls,
    list_documents,
    load_dotenv,
    percent,
    score_case,
    short_snippet,
    stream_chatflow,
)


BASELINE = {
    "name": "第一版自动生成 20 题",
    "cases": 20,
    "macro_recall": 0.93,
    "macro_precision": 0.977,
    "macro_answer_recall": 0.94,
    "bad_cases": 2,
}


def load_manual_cases(path: Path) -> list[EvalCase]:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    cases: list[EvalCase] = []
    for index, item in enumerate(payload, start=1):
        cases.append(
            EvalCase(
                case_id=str(item.get("id") or f"manual-{index:02d}"),
                query=str(item["query"]),
                expected_doc=str(item["expected_doc"]),
                expected_terms=[str(term) for term in item["expected_terms"]],
                source_segment_id="manual-ground-truth",
                source_snippet="人工 Ground Truth",
            )
        )
    return cases


def macro(rows: list[dict[str, Any]], key: str) -> float:
    return sum(row["score"][key] for row in rows) / len(rows) if rows else 0.0


def weighted_average(left_value: float, left_count: int, right_value: float, right_count: int) -> float:
    total = left_count + right_count
    return ((left_value * left_count) + (right_value * right_count)) / total if total else 0.0


def write_combined_report(
    output: Path,
    *,
    documents: list[Document],
    manual_cases: list[EvalCase],
    rows: list[dict[str, Any]],
    threshold: float,
) -> None:
    manual_recall = macro(rows, "recall")
    manual_precision = macro(rows, "precision")
    manual_answer = macro(rows, "answer_recall")
    manual_bad = [row for row in rows if row["score"]["recall"] < threshold or row["score"]["precision"] < threshold]

    total_cases = BASELINE["cases"] + len(rows)
    combined_recall = weighted_average(BASELINE["macro_recall"], BASELINE["cases"], manual_recall, len(rows))
    combined_precision = weighted_average(BASELINE["macro_precision"], BASELINE["cases"], manual_precision, len(rows))
    combined_answer = weighted_average(BASELINE["macro_answer_recall"], BASELINE["cases"], manual_answer, len(rows))
    combined_bad = int(BASELINE["bad_cases"]) + len(manual_bad)

    lines: list[str] = []
    lines.append("# CloudRAG Chatflow 召回率与准确率组合测试结果")
    lines.append("")
    lines.append(f"- 测试时间：{time.strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append("- 测试方式：人工 Ground Truth 问题通过 Dify Chatflow `/chat-messages` 完整链路执行；不直接调用知识库检索 API。")
    lines.append("- 组合方式：第一版 20 题指标作为 baseline，和本次 30 条人工 Ground Truth 按用例数加权合并。")
    lines.append(f"- 通过阈值：Recall >= {percent(threshold)}，Precision >= {percent(threshold)}")
    lines.append("")

    lines.append("## 总体结论")
    lines.append("")
    lines.append("| 数据集 | 用例数 | Recall | Precision | Answer覆盖 | Bad Case |")
    lines.append("|---|---:|---:|---:|---:|---:|")
    lines.append(
        f"| {BASELINE['name']} | {BASELINE['cases']} | {percent(BASELINE['macro_recall'])} | "
        f"{percent(BASELINE['macro_precision'])} | {percent(BASELINE['macro_answer_recall'])} | {BASELINE['bad_cases']} |"
    )
    lines.append(
        f"| 人工 Ground Truth 30 题 | {len(rows)} | {percent(manual_recall)} | "
        f"{percent(manual_precision)} | {percent(manual_answer)} | {len(manual_bad)} |"
    )
    lines.append(
        f"| 合并结果 | {total_cases} | {percent(combined_recall)} | "
        f"{percent(combined_precision)} | {percent(combined_answer)} | {combined_bad} |"
    )
    lines.append("")

    lines.append("## 当前 Dify 知识库文档")
    lines.append("")
    lines.append("| 序号 | 文档名 | 索引状态 |")
    lines.append("|---:|---|---|")
    for index, document in enumerate(documents, start=1):
        lines.append(f"| {index} | {document.name} | {document.status} |")
    lines.append("")

    lines.append("## 人工 Ground Truth 30 题明细")
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
    if not manual_bad:
        lines.append("人工 Ground Truth 30 题无 Bad Case。")
    for row in manual_bad:
        case: EvalCase = row["case"]
        result: ChatflowResult = row["result"]
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
        lines.append(f"- 答案摘要：{short_snippet(result.answer, 360) if result.answer else '无'}")
        lines.append("- 返回 Chunk：")
        if not result.chunks:
            lines.append("  - 无")
        for idx, chunk in enumerate(result.chunks[:6], start=1):
            lines.append(f"  - {idx}. `{chunk.get('document_name')}` score={chunk.get('score')}：{chunk.get('snippet')}")
        lines.append("")

    lines.append("## 人工 Ground Truth 用例")
    lines.append("")
    for case in manual_cases:
        lines.append(f"### {case.case_id}")
        lines.append("")
        lines.append(f"- Query：{case.query}")
        lines.append(f"- Expected Doc：{case.expected_doc}")
        lines.append(f"- Expected Terms：{', '.join(case.expected_terms)}")
        lines.append("")

    output.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    load_dotenv(Path(".env"))
    base_url = os.getenv("DIFY_BASE_URL", "")
    dataset_key = os.getenv("DIFY_DATASET_API_KEY", "")
    dataset_id = os.getenv("DIFY_DATASET_ID", "")
    app_key = os.getenv("DIFY_API_KEY", "")
    base_urls = candidate_base_urls(os.getenv("EVAL_DIFY_BASE_URL", "http://localhost/v1") or base_url)
    threshold = float(os.getenv("EVAL_THRESHOLD", "0.80"))
    timeout = int(os.getenv("EVAL_TIMEOUT_SECONDS", "120"))
    cases_path = Path("reports/manual_ground_truth_30.json")
    output = Path("测试结果.md")

    missing = [name for name, value in {
        "DIFY_DATASET_API_KEY": dataset_key,
        "DIFY_DATASET_ID": dataset_id,
        "DIFY_API_KEY": app_key,
    }.items() if not value]
    if missing:
        raise SystemExit(f"缺少配置：{', '.join(missing)}")

    documents, error = list_documents(base_urls, dataset_id, dataset_key, timeout)
    if not documents:
        raise SystemExit(f"无法读取知识库文档：{error}")

    manual_cases = load_manual_cases(cases_path)
    rows: list[dict[str, Any]] = []
    print(f"开始人工 Ground Truth Chatflow 评测：{len(manual_cases)} 条")
    for index, case in enumerate(manual_cases, start=1):
        print(f"[{index}/{len(manual_cases)}] {case.case_id} {case.query}")
        result = stream_chatflow(base_urls, app_key, case.query, timeout, user=f"cloudrag-manual-eval-{index}")
        score = score_case(case, result)
        rows.append({"case": case, "result": result, "score": score})
        print(
            f"  Recall={percent(score['recall'])}, Precision={percent(score['precision'])}, "
            f"Answer={percent(score['answer_recall'])}, chunks={score['returned_count']}"
        )

    write_combined_report(output, documents=documents, manual_cases=manual_cases, rows=rows, threshold=threshold)
    print(f"组合测试报告已生成：{output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
