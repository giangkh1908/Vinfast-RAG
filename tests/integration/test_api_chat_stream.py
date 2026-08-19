"""Integration tests for POST /api/chat/stream SSE endpoint."""

import json
import uuid
from unittest.mock import AsyncMock

import pytest


class TestApiChatStreamIntegration:
    """Test /api/chat/stream SSE streaming endpoint with AsyncClient."""

    @pytest.mark.asyncio
    async def test_chat_stream_success_events(self, async_client, monkeypatch):
        async def fake_stream(*args, **kwargs):
            yield {"type": "decision", "content": "answer"}
            yield {"type": "classify", "content": {"specificity": "clear", "entities": {"model": "VF 8"}}}
            yield {"type": "status", "content": "Đang tra cứu dữ liệu…"}
            yield {"type": "tool_call", "content": {"tool": "get_price", "success": True}}
            yield {"type": "token", "content": "VF 8 có "}
            yield {"type": "token", "content": "giá từ 1.090.000.000 VNĐ."}
            yield {"type": "sources", "content": [{"source_url": "https://shop.vinfastauto.com"}]}
            yield {"type": "done"}

        monkeypatch.setattr("app.agent.agent_loop.AgentLoop.run_stream", fake_stream)
        monkeypatch.setattr(
            "app.core.storage.session_store.get_session", AsyncMock(return_value={"summary": None, "turn_count": 0})
        )
        monkeypatch.setattr("app.core.storage.session_store.touch_session", AsyncMock())

        valid_session_id = str(uuid.uuid4())
        payload = {
            "session_id": valid_session_id,
            "message": "VF 8 giá bao nhiêu?",
            "history": [],
        }

        response = await async_client.post("/api/chat/stream", json=payload)
        assert response.status_code == 200
        assert "text/event-stream" in response.headers.get("content-type", "")

        # Parse SSE stream content
        body_text = response.text
        lines = [line.strip() for line in body_text.split("\n") if line.startswith("data: ")]
        assert len(lines) >= 6

        events = [json.loads(line.replace("data: ", "")) for line in lines]
        event_types = [ev.get("type") for ev in events]

        assert "decision" in event_types
        assert "classify" in event_types
        assert "tool_call" in event_types
        assert "token" in event_types
        assert "done" in event_types

        # Verify token sequence
        tokens = [ev.get("content") for ev in events if ev.get("type") == "token"]
        assert "".join(tokens) == "VF 8 có giá từ 1.090.000.000 VNĐ."

    @pytest.mark.asyncio
    async def test_chat_stream_deduplication_409(self, async_client, monkeypatch):
        async def fake_stream(*args, **kwargs):
            yield {"type": "decision", "content": "answer"}
            yield {"type": "token", "content": "Hi"}
            yield {"type": "done"}

        monkeypatch.setattr("app.agent.agent_loop.AgentLoop.run_stream", fake_stream)
        monkeypatch.setattr(
            "app.core.storage.session_store.get_session", AsyncMock(return_value={"summary": None, "turn_count": 0})
        )
        monkeypatch.setattr("app.core.storage.session_store.touch_session", AsyncMock())

        valid_session_id = str(uuid.uuid4())
        msg_id = str(uuid.uuid4())
        payload = {
            "session_id": valid_session_id,
            "message": "VF 8 giá bao nhiêu?",
            "history": [],
            "message_id": msg_id,
        }

        # First request: 200 OK text/event-stream
        res1 = await async_client.post("/api/chat/stream", json=payload)
        assert res1.status_code == 200

        # Second duplicate request: 409 Conflict JSON
        res2 = await async_client.post("/api/chat/stream", json=payload)
        assert res2.status_code == 409
        assert "Tin nhắn trùng lặp" in res2.json().get("error", "")

    @pytest.mark.asyncio
    async def test_chat_stream_error_event(self, async_client, monkeypatch):
        # Fake generator that raises error during streaming
        async def fake_error_stream(*args, **kwargs):
            yield {"type": "decision", "content": "answer"}
            yield {"type": "error", "content": "Lỗi kết nối AI model"}
            yield {"type": "done"}

        monkeypatch.setattr("app.agent.agent_loop.AgentLoop.run_stream", fake_error_stream)
        monkeypatch.setattr(
            "app.core.storage.session_store.get_session", AsyncMock(return_value={"summary": None, "turn_count": 0})
        )
        monkeypatch.setattr("app.core.storage.session_store.touch_session", AsyncMock())

        valid_session_id = str(uuid.uuid4())
        payload = {
            "session_id": valid_session_id,
            "message": "VF 8 lỗi",
            "history": [],
        }

        response = await async_client.post("/api/chat/stream", json=payload)
        assert response.status_code == 200

        body_text = response.text
        lines = [line.strip() for line in body_text.split("\n") if line.startswith("data: ")]
        events = [json.loads(line.replace("data: ", "")) for line in lines]
        event_types = [ev.get("type") for ev in events]

        assert "error" in event_types
        error_ev = next(ev for ev in events if ev.get("type") == "error")
        assert "Lỗi kết nối AI model" in error_ev.get("content", "")
