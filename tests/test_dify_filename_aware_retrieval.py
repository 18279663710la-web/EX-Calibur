import json

import pytest


async def _collect_async(generator):
    return [item async for item in generator]


@pytest.mark.asyncio
async def test_chat_stream_forwards_original_query_to_dify_without_filename_rewrite(monkeypatch):
    from src.models.chat import ChatRequest
    from src.services import dify

    payloads = []

    class FakeResponse:
        status_code = 200

        async def aread(self):
            return b""

        async def aiter_lines(self):
            yield 'data: {"event":"text_chunk","data":{"text":"找到代码。"}}'
            yield 'data: {"event":"workflow_finished","data":{"total_tokens":1,"elapsed_time":0.01}}'

    class FakeStream:
        def __init__(self, method, url, headers=None, content=None):
            payloads.append(json.loads(content.decode("utf-8")))

        async def __aenter__(self):
            return FakeResponse()

        async def __aexit__(self, exc_type, exc, tb):
            return False

    class FakeClient:
        def __init__(self, timeout=None):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        def stream(self, method, url, headers=None, content=None):
            return FakeStream(method, url, headers=headers, content=content)

    monkeypatch.setattr(dify.httpx, "AsyncClient", FakeClient)

    request = ChatRequest(
        conversation_id="11111111-1111-1111-1111-111111111111",
        query="帮我找一下数据安全实验报告五里的所有代码",
    )

    await _collect_async(
        dify.chat_stream(
            user_id="22222222-2222-2222-2222-222222222222",
            username="admin",
            request=request,
        )
    )

    assert payloads
    assert payloads[0]["query"] == request.query
    assert payloads[0]["inputs"]["userinput"]["query"] == request.query
    assert "指定文档" not in json.dumps(payloads[0], ensure_ascii=False)
    assert "system_prompt" not in payloads[0]["inputs"]


@pytest.mark.asyncio
async def test_chat_stream_filters_dify_think_blocks_before_frontend(monkeypatch):
    from src.models.chat import ChatRequest
    from src.services import dify

    class FakeResponse:
        status_code = 200

        async def aread(self):
            return b""

        async def aiter_lines(self):
            yield 'data: {"event":"text_chunk","data":{"text":"<think>hidden"}}'
            yield 'data: {"event":"text_chunk","data":{"text":" reasoning</think>正式回答"}}'
            yield 'data: {"event":"workflow_finished","data":{"total_tokens":1,"elapsed_time":0.01}}'

    class FakeStream:
        async def __aenter__(self):
            return FakeResponse()

        async def __aexit__(self, exc_type, exc, tb):
            return False

    class FakeClient:
        def __init__(self, timeout=None):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        def stream(self, method, url, headers=None, content=None):
            return FakeStream()

    monkeypatch.setattr(dify.httpx, "AsyncClient", FakeClient)

    events = await _collect_async(
        dify.chat_stream(
            user_id="user-1",
            username="admin",
            request=ChatRequest(query="测试"),
        )
    )

    joined = "".join(events)
    assert "正式回答" in joined
    assert "hidden" not in joined
    assert "<think>" not in joined
    assert "</think>" not in joined


@pytest.mark.asyncio
async def test_chat_stream_surfaces_dify_failed_workflow_as_error(monkeypatch):
    from src.models.chat import ChatRequest
    from src.services import dify

    class FakeResponse:
        status_code = 200

        async def aread(self):
            return b""

        async def aiter_lines(self):
            yield 'data: {"event":"workflow_finished","data":{"status":"failed","error":"Request failed with status code 404","total_tokens":1}}'

    class FakeStream:
        async def __aenter__(self):
            return FakeResponse()

        async def __aexit__(self, exc_type, exc, tb):
            return False

    class FakeClient:
        def __init__(self, timeout=None):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        def stream(self, method, url, headers=None, content=None):
            return FakeStream()

    monkeypatch.setattr(dify.httpx, "AsyncClient", FakeClient)

    events = await _collect_async(
        dify.chat_stream(
            user_id="user-1",
            username="admin",
            request=ChatRequest(query="1"),
        )
    )

    joined = "".join(events)
    assert "event: error" in joined
    assert "Request failed with status code 404" in joined
    assert "event: done" not in joined


@pytest.mark.asyncio
async def test_chat_stream_uses_dify_conversation_id_for_followup_turns(monkeypatch):
    from src.models.chat import ChatRequest
    from src.services import dify

    class FakeResponse:
        status_code = 200

        async def aread(self):
            return b""

        async def aiter_lines(self):
            yield 'data: {"event":"agent_message","conversation_id":"dify-conv-1","answer":"ok"}'
            yield 'data: {"event":"message_end","conversation_id":"dify-conv-1","metadata":{"usage":{"total_tokens":1}}}'

    class FakeStream:
        async def __aenter__(self):
            return FakeResponse()

        async def __aexit__(self, exc_type, exc, tb):
            return False

    class FakeClient:
        def __init__(self, timeout=None):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        def stream(self, method, url, headers=None, content=None):
            return FakeStream()

    monkeypatch.setattr(dify.httpx, "AsyncClient", FakeClient)

    events = await _collect_async(
        dify.chat_stream(
            user_id="user-1",
            username="admin",
            request=ChatRequest(query="测试"),
        )
    )

    joined = "".join(events)
    assert '"conversation_id": "dify-conv-1"' in joined
    assert "ok" in joined
