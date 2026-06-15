from __future__ import annotations

import importlib
from pathlib import Path

from fastapi.testclient import TestClient


def test_agent_server_uses_configurable_knowledge_dir(monkeypatch, tmp_path):
    knowledge_dir = tmp_path / "knowledge"
    knowledge_dir.mkdir()
    (knowledge_dir / "架构文档.md").write_text("mobile architecture", encoding="utf-8")

    monkeypatch.setenv("AGENT_KNOWLEDGE_DIR", str(knowledge_dir))

    agent_server = importlib.import_module("agent_server")
    client = TestClient(agent_server.app)

    response = client.post("/search", json={"keyword": "架构", "top_k": 3})

    assert response.status_code == 200
    payload = response.json()
    assert payload["count"] == 1
    assert payload["files"][0]["filename"] == "架构文档.md"


def test_agent_server_default_port_does_not_conflict_with_backend():
    agent_server = importlib.import_module("agent_server")

    assert agent_server.get_agent_port() == 8090


def test_docker_compose_starts_agent_server_with_project_services():
    compose = Path("docker-compose.yml").read_text(encoding="utf-8")

    assert "agent-server:" in compose
    assert "dockerfile: agent-server.Dockerfile" in compose
    assert '"${AGENT_PORT:-8090}:8090"' in compose
    assert "- agent-server" in compose
