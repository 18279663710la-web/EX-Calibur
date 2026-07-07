import importlib


MODEL_ENV_NAMES = [
    "CLEANING_MODEL_API_KEY",
    "CLEANING_MODEL_BASE_URL",
    "CLEANING_MODEL_NAME",
    "DEEPSEEK_API_KEY",
    "CLOUDRAG_DEEPSEEK_API_KEY",
    "DEEPSEEK_BASE_URL",
    "DEEPSEEK_MODEL",
]


def reload_sync_script(monkeypatch):
    for name in MODEL_ENV_NAMES:
        monkeypatch.delenv(name, raising=False)
    import sync_script

    return importlib.reload(sync_script)


def test_cleaning_model_config_prefers_generic_env(monkeypatch):
    sync_script = reload_sync_script(monkeypatch)
    monkeypatch.setenv("CLEANING_MODEL_API_KEY", "generic-key")
    monkeypatch.setenv("CLEANING_MODEL_BASE_URL", "https://models.example/v1")
    monkeypatch.setenv("CLEANING_MODEL_NAME", "qwen-plus")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "legacy-key")
    monkeypatch.setenv("DEEPSEEK_BASE_URL", "https://legacy.example/v1")
    monkeypatch.setenv("DEEPSEEK_MODEL", "deepseek-chat")

    sync_script = importlib.reload(sync_script)

    assert sync_script.CLEANING_MODEL_API_KEY == "generic-key"
    assert sync_script.CLEANING_MODEL_BASE_URL == "https://models.example/v1"
    assert sync_script.CLEANING_MODEL_NAME == "qwen-plus"


def test_cleaning_model_config_falls_back_to_legacy_deepseek_env(monkeypatch):
    sync_script = reload_sync_script(monkeypatch)
    monkeypatch.setenv("CLOUDRAG_DEEPSEEK_API_KEY", "legacy-cloudrag-key")
    monkeypatch.setenv("DEEPSEEK_BASE_URL", "https://legacy.example/v1")
    monkeypatch.setenv("DEEPSEEK_MODEL", "deepseek-chat")

    sync_script = importlib.reload(sync_script)

    assert sync_script.CLEANING_MODEL_API_KEY == "legacy-cloudrag-key"
    assert sync_script.CLEANING_MODEL_BASE_URL == "https://legacy.example/v1"
    assert sync_script.CLEANING_MODEL_NAME == "deepseek-chat"


def test_model_pipeline_builds_cleaned_markdown_candidate(tmp_path, monkeypatch):
    sync_script = reload_sync_script(monkeypatch)
    source_dir = tmp_path / "knowledge"
    archive_dir = tmp_path / "structured_markdown"
    source_dir.mkdir()
    source_file = source_dir / "note.txt"
    source_file.write_text("raw note", encoding="utf-8")
    file_state = sync_script.describe_file(source_file, source_dir)

    class FakeCleaner:
        def clean(self, raw_text):
            return f"## cleaned\n{raw_text}"

    candidates = sync_script.build_upload_candidates(
        [file_state],
        pipeline="model",
        archive_dir=archive_dir,
        cleaner=FakeCleaner(),
        ledger={},
    )

    assert len(candidates) == 1
    assert candidates[0].upload_path == archive_dir / "note.md"
    markdown = candidates[0].upload_path.read_text(encoding="utf-8")
    assert markdown.startswith("## note - cleaned\n")
    assert "raw note" in markdown
