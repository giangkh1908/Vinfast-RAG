import logging
import time

from app.agent.graph import get_compiled_graph
from app.agent.nodes.respond import AgentResult

logger = logging.getLogger("bds.agent")


class AgentLoop:
    def __init__(self):
        self.graph = get_compiled_graph()

    async def run(self, query: str, history: list[dict]) -> AgentResult:
        state = {
            "query": query,
            "history": history,
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
        return result

    async def run_stream(self, query: str, history: list[dict]):
        state = {
            "query": query,
            "history": history,
            "t0": time.time(),
        }

        yielded_classify = False
        yielded_tokens = False

        async for event in self.graph.astream(state, stream_mode="updates"):
            for node_name, node_output in event.items():
                if node_name == "classify":
                    dec = node_output.get("decision", "answer")
                    yield {"type": "decision", "content": dec}
                    yield {"type": "classify", "content": {
                        "specificity": node_output.get("specificity", ""),
                        "entities": node_output.get("entities", {}),
                    }}
                    yielded_classify = True

                elif node_name == "execute_tools":
                    for tr in node_output.get("tool_results", []):
                        yield {"type": "tool_call", "content": {"tool": tr["tool"], "success": tr["success"]}}

                elif node_name == "generate":
                    fr = node_output.get("final_response", "")
                    if fr:
                        yield {"type": "token", "content": fr}
                        yielded_tokens = True

                elif node_name == "validate":
                    pass

                elif node_name == "respond":
                    result = node_output.get("result")
                    if result is None:
                        continue

                    if result.decision == "out_of_scope":
                        yield {"type": "answer", "content": result.response}
                    elif result.decision == "clarify":
                        yield {"type": "clarify", "content": result.response}
                        yield {"type": "sources", "content": []}
                    elif result.decision == "refuse":
                        if not yielded_tokens:
                            yield {"type": "token", "content": result.response}
                    elif not yielded_tokens:
                        yield {"type": "token", "content": result.response}

                    if result.sources and result.decision == "answer":
                        seen = set()
                        formatted = []
                        for c in sorted(result.sources, key=lambda x: x.get("score", 0), reverse=True):
                            url = c.get("source_url", "")
                            if not url or not url.startswith("http") or url in seen:
                                continue
                            seen.add(url)
                            model = c.get("model_code", "")
                            label = c.get("source_type", "")
                            score = round(c.get("score", 0), 3)
                            text = f"{model} — {label}" if model and label else (label or url)
                            formatted.append({"text": text, "url": url, "type": label, "score": score})
                            if len(formatted) >= 5:
                                break
                        if formatted:
                            yield {"type": "sources", "content": formatted}

        yield {"type": "done"}
