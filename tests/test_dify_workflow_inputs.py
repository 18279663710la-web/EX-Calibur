import json

from src.models.chat import ChatRequest
from src.services.dify import build_chat_messages_body, build_dify_inputs, build_workflow_body


def test_build_dify_inputs_forwards_user_payload_without_backend_rag_logic():
    request = ChatRequest(
        query="总结这份材料",
        file_ids=["upload-file-a", "upload-file-b"],
    )

    inputs = build_dify_inputs(request)

    assert inputs["query"] == "总结这份材料"
    assert inputs["file_ids"] == "upload-file-a,upload-file-b"
    assert inputs["files"] == [
        {
            "type": "document",
            "transfer_method": "local_file",
            "upload_file_id": "upload-file-a",
        },
        {
            "type": "document",
            "transfer_method": "local_file",
            "upload_file_id": "upload-file-b",
        },
    ]
    assert "system_prompt" not in inputs
    assert "top_k" not in inputs
    assert "score_threshold" not in inputs
    assert "rerank_enabled" not in inputs


def test_workflow_body_uses_dify_file_contract_and_streaming_mode():
    request = ChatRequest(query="分析附件", file_ids=["dify-upload-id"])

    body = build_workflow_body(request, user="admin")

    assert body["response_mode"] == "streaming"
    assert body["user"] == "admin"
    assert body["inputs"]["query"] == "分析附件"
    assert body["files"] == [
        {
            "type": "document",
            "transfer_method": "local_file",
            "upload_file_id": "dify-upload-id",
        }
    ]


def test_chat_messages_body_uses_chatflow_contract():
    request = ChatRequest(query="分析附件", file_ids=["dify-upload-id"])

    body = build_chat_messages_body(request, user="admin")

    assert body["query"] == "分析附件"
    assert body["response_mode"] == "streaming"
    assert body["user"] == "admin"
    assert body["inputs"] == {
        "userinput": {
            "query": "分析附件",
            "files": [
                {
                    "type": "document",
                    "transfer_method": "local_file",
                    "upload_file_id": "dify-upload-id",
                }
            ],
        }
    }
    assert body["files"] == [
        {
            "type": "document",
            "transfer_method": "local_file",
            "upload_file_id": "dify-upload-id",
        }
    ]


def test_dify_body_serialization_preserves_chinese_characters():
    request = ChatRequest(query="帮我总结这份数据安全实验报告")
    body = build_workflow_body(request, user="test")

    httpx_default = json.dumps(body, ensure_ascii=True)
    utf8_safe = json.dumps(body, ensure_ascii=False)

    assert "\\u" in httpx_default
    assert "帮我总结这份数据安全实验报告" in utf8_safe
    assert "\\u" not in utf8_safe
