"""
Generate a real decision log and output as JSON.

Run: python tests/gen_log.py
Optional: python tests/gen_log.py "vf6 eco công suất bao nhiêu"
"""

import asyncio
import io
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")


async def main():
    from app.agent.agent_loop import AgentLoop
    from app.agent.decision import log_store

    query = sys.argv[1] if len(sys.argv) > 1 else "VF 6 có những phiên bản nào?"

    log_store.clear()
    log_store.start_run()

    agent = AgentLoop()
    _ = await agent.run(query, [])

    logs = log_store.get_all()
    if logs:
        print(json.dumps(logs[0], ensure_ascii=False, indent=2))
    else:
        print("NO LOG GENERATED")


asyncio.run(main())
