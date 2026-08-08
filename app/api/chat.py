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

from fastapi.responses import JSONResponse, StreamingResponse as SR
from app.agent.decision import log_store


@router.get("/api/logs")
async def get_logs(run_id: str = None):
    if run_id:
        logs = log_store.get_by_run(run_id)
    else:
        logs = log_store.get_all()
    return JSONResponse(content={"count": len(logs), "run_id": run_id, "logs": logs})


@router.get("/api/logs/export")
async def export_logs(run_id: str = None):
    if run_id:
        logs = log_store.get_by_run(run_id)
    else:
        logs = log_store.get_all()
    lines = [json.dumps(l, ensure_ascii=False) for l in logs]
    content = "\n".join(lines) + "\n" if lines else ""
    fname = "logs_" + (run_id or "all") + ".jsonl"
    return SR(
        content=iter([content]),
        media_type="application/x-ndjson",
        headers={"Content-Disposition": "attachment; filename=" + fname},
    )
