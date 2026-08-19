import asyncio
import logging
import time

from app.agent.classifier import get_classifier
from app.agent.graph import get_compiled_graph
from app.agent.intent import classify_intent
from app.agent.llm import USER_INPUT_MAX_TOKENS, truncate_text
from app.agent.nodes.respond import AgentResult
from app.core.storage.cache import ANS_TTL, cache, make_answer_key, make_exact_io_key

logger = logging.getLogger("bds.agent")

_HEARTBEAT_S = 3.0


def _is_cacheable(history: list[dict], session_id: str, intent: str) -> bool:
    """Kiểm tra điều kiện cache: single-turn, có session_id, intent rõ ràng"""
    # Single-turn: history rỗng
    if history:
        return False

    # Có session_id
    if not session_id:
        return False

    # Intent rõ ràng (không phải greeting, clarify, out_of_scope)
    non_cacheable_intents = {"out_of_scope", "greeting", "chitchat", "clarify"}
    if intent in non_cacheable_intents:
        return False

    return True


class AgentLoop:
    def __init__(self):
        self.graph = get_compiled_graph()

    async def run(
        self,
        query: str,
        history: list[dict],
        *,
        summary: str | None = None,
        session_id: str = "",
    ) -> AgentResult:
        # Cap input người dùng: cắt đuôi nếu vượt token budget
        query = truncate_text(query, USER_INPUT_MAX_TOKENS)

        # 1. Exact I/O Cache: Kiểm tra ngay input -> output bất kể single hay multi-turn
        io_key = make_exact_io_key(query)
        if cache.enabled:
            cached_io = await cache.get_json(io_key)
            if cached_io:
                resp_text = cached_io if isinstance(cached_io, str) else cached_io.get("response", "")
                sources = cached_io.get("sources", []) if isinstance(cached_io, dict) else []
                return AgentResult(
                    response=resp_text,
                    sources=sources,
                    decision="answer",
                    classify_result={
                        "decision": "answer",
                        "reason_code": "exact_io_cache_hit",
                    },
                )

        # Fast classify để extract entities và intent (deterministic, không LLM)
        classifier = get_classifier()
        model, version = classifier._detect_model(query)
        intent = classify_intent(query, topic="general")

        # Build entities dict cho cache key
        entities = {}
        if model:
            entities["model"] = model
        if version:
            entities["version"] = version
        entities["intent"] = intent

        # Check cacheability
        cacheable = _is_cacheable(history, session_id, intent)

        # Check cache nếu cacheable và cache enabled
        # cache_key=None khi PG unreachable → skip cache
        if cacheable and cache.enabled:
            cache_key = await make_answer_key(
                entities=entities,
                query=query,
            )

            if cache_key is not None:
                cached = await cache.get_json(cache_key)
                if cached:
                    # Cache hit - trả về cached result
                    return AgentResult(
                        response=cached["response"],
                        sources=cached.get("sources", []),
                        decision=cached.get("decision", "answer"),
                        classify_result={
                            "decision": "answer",
                            "reason_code": "cache_hit",
                            "entities": entities,
                        },
                    )
        else:
            cache_key = None

        # Cache miss hoặc không cacheable - chạy graph bình thường
        state = {
            "query": query,
            "history": history,
            "summary": summary,
            "session_id": session_id,
            "t0": time.time(),
        }
        final = await self.graph.ainvoke(state)
        result = final.get("result")
        if result is None:
            return AgentResult(
                response="Mình chưa thể hoàn tất câu trả lời lúc này.",
                decision="refuse",
                classify_result={"decision": "refuse", "reason_code": "system_error"},
            )

        # Exact I/O Cache write: lưu input user -> output text cho mọi lần hỏi sau (bất kể single/multi-turn)
        if cache.enabled and result.decision == "answer" and result.response:
            await cache.set_json(
                io_key,
                {
                    "response": result.response,
                    "sources": result.sources,
                    "decision": result.decision,
                },
                ttl=ANS_TTL,
            )

        # Answer Cache write: chỉ cache khi cacheable và decision là "answer"
        # cache_key=None khi PG unreachable → skip cache write
        if cacheable and cache.enabled and result.decision == "answer" and cache_key is not None:
            await cache.set_json(
                cache_key,
                {
                    "response": result.response,
                    "sources": result.sources,
                    "decision": result.decision,
                },
                ttl=ANS_TTL,
            )

        return result

    async def run_stream(
        self,
        query: str,
        history: list[dict],
        *,
        summary: str | None = None,
        session_id: str = "",
    ):
        """True streaming: token LLM được node đẩy ra qua custom stream mode
        (get_stream_writer) ngay khi sinh, không chờ node kết thúc.

        Fix so với bản cũ:
        - Answer stream từng token thay vì 1 block cuối luồng
        - tool_call hết duplicate (node trả tool_results lũy tiến → chỉ phát phần mới)
        - Heartbeat ping mỗi 3s im lặng (chống proxy/client ngắt kết nối)
        - Lỗi giữa stream → event {type: error} thay vì chết lặng lẽ
        - Không phát lại cả câu ở respond nếu token đã stream rồi
        """
        query = truncate_text(query, USER_INPUT_MAX_TOKENS)

        # 1. Exact I/O Cache: Kiểm tra ngay input -> output bất kể single hay multi-turn
        io_key = make_exact_io_key(query)
        if cache.enabled:
            cached_io = await cache.get_json(io_key)
            if cached_io:
                resp_text = cached_io if isinstance(cached_io, str) else cached_io.get("response", "")
                yield {"type": "decision", "content": "answer"}
                yield {
                    "type": "classify",
                    "content": {
                        "specificity": "exact",
                        "entities": {"cache": "exact_io_hit"},
                    },
                }
                yield {"type": "token", "content": resp_text}
                yield {"type": "done"}
                return

        # Fast classify để extract entities và intent (deterministic, không LLM)
        classifier = get_classifier()
        model, version = classifier._detect_model(query)
        intent = classify_intent(query, topic="general")

        # Build entities dict cho cache key
        entities = {}
        if model:
            entities["model"] = model
        if version:
            entities["version"] = version
        entities["intent"] = intent

        # Check cacheability
        cacheable = _is_cacheable(history, session_id, intent)
        cache_key = None  # sẽ set bên dưới nếu cacheable

        # Check cache nếu cacheable và cache enabled
        # cache_key=None khi PG unreachable → skip cache
        if cacheable and cache.enabled:
            cache_key = await make_answer_key(
                entities=entities,
                query=query,
            )

            if cache_key is not None:
                cached = await cache.get_json(cache_key)
                if cached:
                    # Cache hit - replay SSE events
                    response = cached["response"]
                    decision = cached.get("decision", "answer")

                    # Yield SSE events (không cần status "Đang tra cứu" vì đã có câu trả lời ngay)
                    yield {"type": "decision", "content": decision}
                    yield {
                        "type": "classify",
                        "content": {
                            "specificity": "exact",
                            "entities": entities,
                        },
                    }
                    yield {"type": "token", "content": response}
                    yield {"type": "done"}
                    return

        # Cache miss hoặc không cacheable - chạy graph bình thường
        state = {
            "query": query,
            "history": history,
            "summary": summary,
            "session_id": session_id,
            "t0": time.time(),
        }

        yielded_tokens = False
        tool_results_seen = 0
        graph_error: Exception | None = None

        queue: asyncio.Queue = asyncio.Queue()
        _SENTINEL = object()

        async def _producer():
            nonlocal graph_error
            try:
                async for mode, payload in self.graph.astream(state, stream_mode=["updates", "custom"]):
                    await queue.put((mode, payload))
            except Exception as e:
                graph_error = e
            finally:
                await queue.put(_SENTINEL)

        task = asyncio.create_task(_producer())

        try:
            while True:
                try:
                    item = await asyncio.wait_for(queue.get(), timeout=_HEARTBEAT_S)
                except TimeoutError:
                    # Heartbeat giữ kết nối SSE trong lúc chờ (tool exec, LLM...)
                    yield {"type": "ping"}
                    continue

                if item is _SENTINEL:
                    break

                mode, payload = item

                # Custom events từ get_stream_writer trong nodes (token LLM)
                if mode == "custom":
                    if isinstance(payload, dict) and payload.get("type") == "token":
                        yielded_tokens = True
                    yield payload
                    continue

                # Updates events — node outputs
                for node_name, node_output in payload.items():
                    if node_name == "classify":
                        yield {"type": "decision", "content": node_output.get("decision", "answer")}
                        yield {
                            "type": "classify",
                            "content": {
                                "specificity": node_output.get("specificity", ""),
                                "entities": node_output.get("entities", {}),
                            },
                        }
                        # Cho client biết đang làm gì trong lúc chờ tool + LLM
                        if node_output.get("decision", "answer") == "answer":
                            yield {"type": "status", "content": "Đang tra cứu dữ liệu…"}

                    elif node_name in ("execute_tools", "direct_fetch"):
                        # tool_results là list LŨY TIẾN → chỉ phát phần mới
                        all_tr = node_output.get("tool_results", [])
                        for tr in all_tr[tool_results_seen:]:
                            # BỎ QUA auto-injected tools (supplementary, không phải primary)
                            # Tránh hiển thị "Đang tra cứu..." SAU khi response đã hoàn thành
                            if tr.get("auto_injected"):
                                continue
                            yield {"type": "tool_call", "content": {"tool": tr["tool"], "success": tr["success"]}}
                        tool_results_seen = len(all_tr)

                    elif node_name == "respond":
                        # Clear status khi response xong
                        yield {"type": "status", "content": ""}
                        result = node_output.get("result")
                        if result is None:
                            continue

                        if result.decision == "out_of_scope":
                            yield {"type": "answer", "content": result.response}
                        elif result.decision == "clarify":
                            yield {"type": "clarify", "content": result.response}
                        elif result.decision == "refuse":
                            if not yielded_tokens:
                                yield {"type": "token", "content": result.response}
                        elif not yielded_tokens:
                            # Fallback: LLM chưa stream được gì (writer unavailable)
                            yield {"type": "token", "content": result.response}
                        elif result.source_url:
                            # Token đã stream rồi → chỉ thêm URL ngắn ở cuối (hỗ trợ nhiều link khi so sánh xe)
                            if result.source_url.startswith("["):
                                yield {"type": "token", "content": "\n\n🔗 Xem thêm: " + result.source_url}
                            else:
                                from app.agent.nodes.respond import source_link_md

                                yield {
                                    "type": "token",
                                    "content": "\n\n🔗 Xem thêm: " + source_link_md(result.source_url),
                                }

                        # Exact I/O Cache write: lưu input user -> output text cho mọi lần hỏi sau (bất kể single/multi-turn)
                        if cache.enabled and result.decision == "answer" and result.response:
                            await cache.set_json(
                                io_key,
                                {
                                    "response": result.response,
                                    "sources": result.sources,
                                    "decision": result.decision,
                                },
                                ttl=ANS_TTL,
                            )

                        # Answer Cache write: chỉ cache khi cacheable và decision là "answer"
                        # cache_key=None khi PG unreachable → skip cache write
                        if cacheable and cache.enabled and result.decision == "answer" and cache_key is not None:
                            await cache.set_json(
                                cache_key,
                                {
                                    "response": result.response,
                                    "sources": result.sources,
                                    "decision": result.decision,
                                },
                                ttl=ANS_TTL,
                            )

            if graph_error is not None:
                logger.error("Stream graph error: %s", graph_error)
                yield {"type": "error", "content": "Có lỗi xảy ra khi xử lý câu hỏi. Vui lòng thử lại."}
        finally:
            if not task.done():
                task.cancel()

        yield {"type": "done"}
