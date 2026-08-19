"""Integration tests for POST /api/chat and log endpoints."""

import uuid
from unittest.mock import AsyncMock

import pytest

from app.agent.nodes.respond import AgentResult


class TestApiChatIntegration:
    """Test /api/chat endpoint with AsyncClient."""

    @pytest.mark.asyncio
    async def test_chat_success_single_turn(self, async_client, monkeypatch):
        # Mock AgentLoop.run to return predictable result
        mock_result = AgentResult(
            response="VF 8 có giá từ 1.090.000.000 VNĐ.",
            sources=[{"source_url": "https://shop.vinfastauto.com", "source_type": "pricing"}],
            decision="answer",
            classify_result={"decision": "answer", "reason_code": "sufficient_direct_evidence"},
            decision_log={"request_id": "req-123", "decision": "answer"},
        )
        monkeypatch.setattr("app.agent.agent_loop.AgentLoop.run", AsyncMock(return_value=mock_result))
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

        response = await async_client.post("/api/chat", json=payload)
        assert response.status_code == 200
        data = response.json()

        assert "response" in data
        assert data["response"] == "VF 8 có giá từ 1.090.000.000 VNĐ."
        assert data["decision"] == "answer"
        assert data["needs_clarification"] is False
        assert data["classify"]["reason_code"] == "sufficient_direct_evidence"

    @pytest.mark.asyncio
    async def test_chat_invalid_session_id_400(self, async_client):
        payload = {
            "session_id": "not-a-valid-uuid",
            "message": "VF 8 giá bao nhiêu?",
            "history": [],
        }
        response = await async_client.post("/api/chat", json=payload)
        assert response.status_code == 400
        data = response.json()
        assert "session_id không hợp lệ" in data.get("detail", "")

    @pytest.mark.asyncio
    async def test_chat_message_too_long_400(self, async_client):
        valid_session_id = str(uuid.uuid4())
        long_message = "A" * 5000  # 1250 tokens > 1000 tokens limit
        payload = {
            "session_id": valid_session_id,
            "message": long_message,
            "history": [],
        }
        response = await async_client.post("/api/chat", json=payload)
        assert response.status_code == 400
        assert "Câu hỏi quá dài" in response.json().get("detail", "")

    @pytest.mark.asyncio
    async def test_chat_history_too_long_400(self, async_client):
        valid_session_id = str(uuid.uuid4())
        long_history = [{"role": "user", "content": "A" * 150000}]  # 37500 tokens > 30000 tokens limit
        payload = {
            "session_id": valid_session_id,
            "message": "VF 8 giá bao nhiêu?",
            "history": long_history,
        }
        response = await async_client.post("/api/chat", json=payload)
        assert response.status_code == 400
        assert "Lịch sử hội thoại quá dài" in response.json().get("detail", "")

    @pytest.mark.asyncio
    async def test_chat_deduplication_409(self, async_client, monkeypatch):
        mock_result = AgentResult(
            response="VF 8 giá từ 1.090.000.000 VNĐ.",
            decision="answer",
            classify_result={"decision": "answer"},
        )
        monkeypatch.setattr("app.agent.agent_loop.AgentLoop.run", AsyncMock(return_value=mock_result))
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

        # First attempt: 200 OK
        res1 = await async_client.post("/api/chat", json=payload)
        assert res1.status_code == 200

        # Second attempt with same message_id: 409 Conflict
        res2 = await async_client.post("/api/chat", json=payload)
        assert res2.status_code == 409
        assert "Tin nhắn trùng lặp" in res2.json().get("error", "")


class TestLogEndpointsIntegration:
    """Test /api/logs and /api/logs/export endpoints."""

    @pytest.mark.asyncio
    async def test_get_logs(self, async_client):
        response = await async_client.get("/api/logs")
        assert response.status_code == 200
        data = response.json()
        assert "count" in data
        assert "logs" in data

    @pytest.mark.asyncio
    async def test_export_logs_ndjson(self, async_client):
        response = await async_client.get("/api/logs/export")
        assert response.status_code == 200
        assert "application/x-ndjson" in response.headers.get("content-type", "")
