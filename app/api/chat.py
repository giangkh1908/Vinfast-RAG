import json

from fastapi import APIRouter
from pydantic import BaseModel

from app.agent.agent_loop import AgentLoop

router = APIRouter()

_agent = None


def get_agent() -> AgentLoop:
    global _agent
    if _agent is None:
        _agent = AgentLoop()
    return _agent


class ChatRequest(BaseModel):
    message: str
    history: list[dict] = []


class ChatResponse(BaseModel):
    response: str
    sources: list[dict] = []
    needs_clarification: bool = False
    classify: dict = {}
    decision: str = "answer"
    decision_log: dict = {}


@router.post("/api/chat")
async def chat(request: ChatRequest):
    agent = get_agent()
    result = await agent.run(request.message, request.history)
    return ChatResponse(
        response=result.response,
        sources=result.sources,
        needs_clarification=result.needs_clarification,
        classify=result.classify_result,
        decision=result.decision,
        decision_log=result.decision_log,
    )


@router.post("/api/chat/stream")
async def chat_stream(request: ChatRequest):
    from fastapi.responses import StreamingResponse

    agent = get_agent()

    async def generate():
        async for event in agent.run_stream(request.message, request.history):
            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")
