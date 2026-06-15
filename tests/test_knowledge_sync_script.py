import json
from pathlib import Path

import pytest

import sync_script


class FakeResponse:
    def __init__(self, payload=None, status_code=200, text="OK"):
        self._payload = payload or {}
        self.status_code = status_code
        self.text = text

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise sync_script.requests.HTTPError(self.text)


class FakeSession:
    def __init__(self, response=None):
        self.response = response or FakeResponse(
            {
                "document": {"id": "doc-123", "name": "example.md"},
                "batch": "batch-123",
            }
        )
        self.posts = []

    def post(self, url, headers=None, files=None, data=None, timeout=None):
        file_tuple = files["file"]
        file_name, file_obj, mime_type = file_tuple
        file_obj.read(1)
        self.posts.append(
            {
                "url": url,
                "headers": headers,
                "file_name": file_name,
                "mime_type": mime_type,
                "data": data,
                "timeout": timeout,
            }
        )
        return self.response


def test_dry_run_reports_files_without_touching_ledger(tmp_path):
    source_dir = tmp_path / "knowledge"
    source_dir.mkdir()
    (source_dir / "guide.md").write_text("# Guide", encoding="utf-8")
    ledger_path = tmp_path / "sync_ledger.json"

    result = sync_script.run_sync(
        source_dir=source_dir,
        ledger_path=ledger_path,
        base_url="http://dify.test/v1",
        dataset_api_key="",
        dataset_id="",
        dry_run=True,
        session=FakeSession(),
    )

    assert result.scanned == 1
    assert result.to_upload == 1
    assert result.uploaded == 0
    assert not ledger_path.exists()


def test_missing_credentials_stop_real_sync_before_upload(tmp_path):
    source_dir = tmp_path / "knowledge"
    source_dir.mkdir()
    (source_dir / "guide.md").write_text("# Guide", encoding="utf-8")
    session = FakeSession()

    with pytest.raises(sync_script.ConfigurationError):
        sync_script.run_sync(
            source_dir=source_dir,
            ledger_path=tmp_path / "sync_ledger.json",
            base_url="http://dify.test/v1",
            dataset_api_key="",
            dataset_id="dataset-123",
            dry_run=False,
            session=session,
        )

    assert session.posts == []


def test_upload_uses_dify_create_document_by_file_contract(tmp_path):
    source_dir = tmp_path / "knowledge"
    source_dir.mkdir()
    file_path = source_dir / "example.md"
    file_path.write_text("# Example", encoding="utf-8")
    ledger_path = tmp_path / "sync_ledger.json"
    session = FakeSession()

    result = sync_script.run_sync(
        source_dir=source_dir,
        ledger_path=ledger_path,
        base_url="http://dify.test/v1/",
        dataset_api_key="secret-key",
        dataset_id="dataset-123",
        dry_run=False,
        session=session,
    )

    assert result.uploaded == 1
    assert session.posts[0]["url"] == (
        "http://dify.test/v1/datasets/dataset-123/document/create-by-file"
    )
    assert session.posts[0]["headers"] == {"Authorization": "Bearer secret-key"}
    assert session.posts[0]["file_name"] == "example.md"
    assert session.posts[0]["mime_type"] == "text/markdown"

    payload = json.loads(session.posts[0]["data"]["data"])
    assert payload == {
        "indexing_technique": "high_quality",
        "doc_form": "text_model",
        "doc_language": "Chinese",
        "process_rule": {"mode": "automatic"},
    }

    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    assert ledger["files"]["example.md"]["status"] == "synced"
    assert ledger["files"]["example.md"]["document_id"] == "doc-123"
    assert ledger["files"]["example.md"]["batch"] == "batch-123"


def test_unchanged_files_are_skipped_from_existing_ledger(tmp_path):
    source_dir = tmp_path / "knowledge"
    source_dir.mkdir()
    file_path = source_dir / "example.md"
    file_path.write_text("# Example", encoding="utf-8")
    file_state = sync_script.describe_file(file_path, source_dir)
    ledger_path = tmp_path / "sync_ledger.json"
    ledger_path.write_text(
        json.dumps(
            {
                "files": {
                    "example.md": {
                        "sha256": file_state.sha256,
                        "size": file_state.size,
                        "status": "synced",
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    session = FakeSession()

    result = sync_script.run_sync(
        source_dir=source_dir,
        ledger_path=ledger_path,
        base_url="http://dify.test/v1",
        dataset_api_key="secret-key",
        dataset_id="dataset-123",
        dry_run=False,
        session=session,
    )

    assert result.skipped == 1
    assert result.uploaded == 0
    assert session.posts == []


def test_direct_ledger_entry_does_not_skip_deepseek_pipeline(tmp_path, monkeypatch):
    source_dir = tmp_path / "knowledge"
    source_dir.mkdir()
    file_path = source_dir / "report.docx"
    file_path.write_bytes(b"fake docx")
    file_state = sync_script.describe_file(file_path, source_dir)
    ledger_path = tmp_path / "sync_ledger.json"
    ledger_path.write_text(
        json.dumps(
            {
                "files": {
                    "report.docx": {
                        "sha256": file_state.sha256,
                        "size": file_state.size,
                        "status": "synced",
                        "pipeline": "direct",
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    class FakeCleaner:
        def clean(self, raw_text):
            return "## 清洗后的报告"

    monkeypatch.setattr(sync_script, "extract_docx_text", lambda path: "raw report")
    session = FakeSession()

    result = sync_script.run_sync(
        source_dir=source_dir,
        ledger_path=ledger_path,
        archive_dir=tmp_path / "structured_markdown",
        base_url="http://dify.test/v1",
        dataset_api_key="dataset-key",
        dataset_id="dataset-123",
        deepseek_api_key="deepseek-key",
        pipeline="deepseek",
        dry_run=False,
        session=session,
        cleaner=FakeCleaner(),
    )

    assert result.uploaded == 1
    assert session.posts[0]["file_name"] == "report.md"


def test_deepseek_pipeline_requires_deepseek_key_before_upload(tmp_path, monkeypatch):
    source_dir = tmp_path / "knowledge"
    source_dir.mkdir()
    (source_dir / "report.docx").write_bytes(b"fake docx")
    session = FakeSession()

    monkeypatch.setattr(sync_script, "extract_docx_text", lambda path: "raw report")

    with pytest.raises(sync_script.ConfigurationError) as exc:
        sync_script.run_sync(
            source_dir=source_dir,
            ledger_path=tmp_path / "sync_ledger.json",
            archive_dir=tmp_path / "structured_markdown",
            base_url="http://dify.test/v1",
            dataset_api_key="dataset-key",
            dataset_id="dataset-123",
            deepseek_api_key="",
            pipeline="deepseek",
            dry_run=False,
            session=session,
        )

    assert "DEEPSEEK_API_KEY" in str(exc.value)
    assert session.posts == []


def test_deepseek_pipeline_uploads_cleaned_markdown_with_custom_segmentation(
    tmp_path, monkeypatch
):
    source_dir = tmp_path / "knowledge"
    source_dir.mkdir()
    (source_dir / "report.docx").write_bytes(b"fake docx")
    ledger_path = tmp_path / "sync_ledger.json"
    archive_dir = tmp_path / "structured_markdown"
    session = FakeSession()

    class FakeCleaner:
        def clean(self, raw_text):
            assert raw_text == "raw report"
            return "## 实验目的\n内容\n\n## 实验步骤\n内容"

    monkeypatch.setattr(sync_script, "extract_docx_text", lambda path: "raw report")

    result = sync_script.run_sync(
        source_dir=source_dir,
        ledger_path=ledger_path,
        archive_dir=archive_dir,
        base_url="http://dify.test/v1",
        dataset_api_key="dataset-key",
        dataset_id="dataset-123",
        deepseek_api_key="deepseek-key",
        pipeline="deepseek",
        dry_run=False,
        session=session,
        cleaner=FakeCleaner(),
    )

    assert result.uploaded == 1
    assert session.posts[0]["file_name"] == "report.md"
    assert session.posts[0]["mime_type"] == "text/markdown"
    assert (archive_dir / "report.md").read_text(encoding="utf-8").startswith("## 实验目的")

    payload = json.loads(session.posts[0]["data"]["data"])
    assert payload == {
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

    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    record = ledger["files"]["report.docx"]
    assert record["status"] == "synced"
    assert record["pipeline"] == "deepseek"
    assert record["generated_file"] == "report.md"


def test_deepseek_pipeline_can_clean_markdown_source(tmp_path):
    source_dir = tmp_path / "knowledge"
    source_dir.mkdir()
    source_file = source_dir / "notes.md"
    source_file.write_text("# 原始笔记", encoding="utf-8")
    session = FakeSession()

    class FakeCleaner:
        def clean(self, raw_text):
            assert raw_text == "# 原始笔记"
            return "## 清洗后的笔记"

    result = sync_script.run_sync(
        source_dir=source_dir,
        ledger_path=tmp_path / "sync_ledger.json",
        archive_dir=tmp_path / "structured_markdown",
        base_url="http://dify.test/v1",
        dataset_api_key="dataset-key",
        dataset_id="dataset-123",
        deepseek_api_key="deepseek-key",
        pipeline="deepseek",
        dry_run=False,
        session=session,
        cleaner=FakeCleaner(),
    )

    assert result.uploaded == 1
    assert session.posts[0]["file_name"] == "notes.md"


def test_deepseek_pipeline_can_clean_pdf_source(tmp_path, monkeypatch):
    source_dir = tmp_path / "knowledge"
    source_dir.mkdir()
    source_file = source_dir / "paper.pdf"
    source_file.write_bytes(b"%PDF fake")
    session = FakeSession()

    class FakeCleaner:
        def clean(self, raw_text):
            assert raw_text == "pdf text"
            return "## 清洗后的 PDF"

    monkeypatch.setattr(sync_script, "extract_pdf_text", lambda path: "pdf text")

    result = sync_script.run_sync(
        source_dir=source_dir,
        ledger_path=tmp_path / "sync_ledger.json",
        archive_dir=tmp_path / "structured_markdown",
        base_url="http://dify.test/v1",
        dataset_api_key="dataset-key",
        dataset_id="dataset-123",
        deepseek_api_key="deepseek-key",
        pipeline="deepseek",
        dry_run=False,
        session=session,
        cleaner=FakeCleaner(),
    )

    assert result.uploaded == 1
    assert session.posts[0]["file_name"] == "paper.md"


def test_deepseek_cleaner_splits_long_text_before_calling_api(monkeypatch):
    calls = []

    class FakeResponse:
        status_code = 200
        reason = "OK"
        text = "OK"

        def __init__(self, content):
            self.content = content

        def json(self):
            return {"choices": [{"message": {"content": self.content}}]}

    def fake_post(url, headers=None, json=None, timeout=None):
        user_message = json["messages"][1]["content"]
        calls.append(user_message)
        return FakeResponse(f"## cleaned {len(calls)}")

    monkeypatch.setattr(sync_script.requests, "post", fake_post)

    cleaner = sync_script.DeepSeekCleaner(
        api_key="deepseek-key",
        base_url="https://deepseek.test/v1",
        model="deepseek-chat",
        chunk_chars=5,
    )

    result = cleaner.clean("1234567890")

    assert result == "## cleaned 1\n\n## cleaned 2"
    assert len(calls) == 2


def test_add_retrieval_hints_injects_source_and_section_terms():
    markdown = "## 移动端架构设计\n正文\n\n## Web 端架构设计\n正文"

    result = sync_script.add_retrieval_hints(markdown, "架构文档.md")

    assert result.count("来源文件：架构文档.md") == 2
    assert "文档名称：架构文档" in result
    assert "章节标题：移动端架构设计" in result
    assert "检索关键词：架构文档 架构文档.md 移动端架构设计 移动端设计 移动端架构" in result
