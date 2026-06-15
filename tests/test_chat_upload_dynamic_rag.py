import io
from unittest.mock import AsyncMock

import pytest
from fastapi import UploadFile


@pytest.mark.asyncio
async def test_chat_upload_proxies_file_to_dify_without_local_rag_processing(monkeypatch):
    from src.routes import chat

    calls = []

    async def fake_upload(file, body, *, user):
        calls.append(
            {
                "filename": file.filename,
                "body": body,
                "user": user,
            }
        )
        return {
            "id": "dify-upload-123",
            "name": file.filename,
            "size": len(body),
            "mime_type": file.content_type,
    }

    monkeypatch.setattr(chat.dify_gateway, "upload_file", fake_upload)

    upload = UploadFile(
        filename="fresh.md",
        file=io.BytesIO(b"# Cloud computing\nGateway only"),
        headers={"content-type": "text/markdown"},
    )

    response = await chat.upload_chat_files(
        files=[upload],
        current_user={"sub": "00000000-0000-0000-0000-000000000003", "username": "admin"},
    )

    assert response["code"] == 201
    assert calls == [
        {
            "filename": "fresh.md",
            "body": b"# Cloud computing\nGateway only",
            "user": "admin",
        }
    ]
    item = response["data"]["items"][0]
    assert item["id"] == "dify-upload-123"
    assert item["rag_mode"] == "forwarded"
    assert item["dedup_status"] == "not_applicable"
    assert response["data"]["file_ids"] == ["dify-upload-123"]
    assert response["data"]["status_message"] is None


@pytest.mark.asyncio
async def test_chat_upload_does_not_call_dynamic_rag_or_database(monkeypatch):
    from src.routes import chat

    async def fail_get_pool():
        raise AssertionError("gateway upload must not touch local database")

    async def fake_upload(file, body, *, user):
        return {"id": "dify-upload-456", "name": file.filename, "size": len(body)}

    monkeypatch.setattr(chat, "get_pool", fail_get_pool, raising=False)
    monkeypatch.setattr(chat.dify_gateway, "upload_file", fake_upload)
    monkeypatch.setattr(
        chat.dynamic_rag,
        "process_chat_upload_file",
        AsyncMock(side_effect=AssertionError("dynamic RAG must not run in gateway mode")),
        raising=False,
    )

    upload = UploadFile(
        filename="note.txt",
        file=io.BytesIO(b"hello"),
        headers={"content-type": "text/plain"},
    )

    response = await chat.upload_chat_files(
        files=[upload],
        current_user={"sub": "user-1", "username": "admin"},
    )

    assert response["code"] == 201
    assert response["data"]["file_ids"] == ["dify-upload-456"]


@pytest.mark.asyncio
async def test_chat_upload_keeps_light_gateway_constraints(monkeypatch):
    from src.routes import chat

    async def fake_upload(file, body, *, user):
        return {"id": "unused"}

    monkeypatch.setattr(chat.dify_gateway, "upload_file", fake_upload)

    upload = UploadFile(
        filename="oversize.md",
        file=io.BytesIO(b"x" * (15 * 1024 * 1024 + 1)),
        headers={"content-type": "text/markdown"},
    )

    response = await chat.upload_chat_files(
        files=[upload],
        current_user={"sub": "user-1", "username": "admin"},
    )

    assert response["code"] == 41301


def test_chat_upload_frontend_exposes_native_picker_and_strict_constraints():
    root = __import__("pathlib").Path(__file__).resolve().parents[1]
    chat_source = (root / "frontend" / "src" / "components" / "ChatView.svelte").read_text(
        encoding="utf-8"
    )
    api_source = (root / "frontend" / "src" / "lib" / "api.ts").read_text(encoding="utf-8")

    assert "MAX_CHAT_UPLOAD_FILES = 5" in chat_source
    assert "MAX_CHAT_UPLOAD_BYTES = 15 * 1024 * 1024" in chat_source
    assert "MAX_DAILY_CHAT_UPLOADS = 20" in chat_source
    assert "CHAT_UPLOAD_ALLOWED_EXTENSIONS" in chat_source
    for ext in ["MARKDOWN", "XLS", "PDF", "PROPERTIES", "TXT", "VTT", "MDX", "CSV", "XLSX", "DOCX", "HTML", "HTM", "MD"]:
        assert ext in chat_source
    assert 'type="file"' in chat_source
    assert "multiple" in chat_source
    assert "accept={CHAT_UPLOAD_ACCEPT}" in chat_source
    assert "fileInput?.click()" in chat_source
    assert "uploadProgress" in chat_source
    assert "uploadBlocker" in chat_source
    assert "toastError(message)" not in chat_source
    assert "bg-black text-white" in chat_source
    assert "border-black" in chat_source
    assert "kbApi.uploadChatFiles" in chat_source
    assert "uploadChatFiles" in api_source
    assert "/knowledge-base/chat/upload" in api_source


def test_chat_send_archives_uploaded_files_into_user_bubble_and_clears_input_state():
    root = __import__("pathlib").Path(__file__).resolve().parents[1]
    chat_source = (root / "frontend" / "src" / "components" / "ChatView.svelte").read_text(
        encoding="utf-8"
    )

    assert "archivedFiles" in chat_source
    assert "syncStatus" in chat_source
    assert "selectedFileIds = []" in chat_source
    assert "selectedFiles = []" in chat_source
    assert "files: archivedFiles" in chat_source
    assert "bg-transparent border border-black p-3 rounded-none flex items-center gap-2" in chat_source
    assert "selectedFileIdsSnapshot" in chat_source
    assert "selectedFilesSnapshot" in chat_source
