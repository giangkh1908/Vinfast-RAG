"""Multi-turn conversation tests — focus vào memory/context theo turn.

Chạy OFFLINE (không LLM/network): stub `llm_classify_fallback` → `classify_node`
chạy thuần rule. Mỗi conversation được chạy turn-by-turn, history được build từ
các turn trước (giống luồng thật), assert:
  - decision (/reason_code khi clarify)
  - model resolve (kế thừa / chuyển model giữa chừng)
  - version follow-up

Cover các bug/sửa đổi trong session:
  - Memory recency: follow-up không nhắc model phải lấy model GẦN NHẤT.
  - Chuyển model qua lại (VF6 → VF8 → VF6).
  - Follow-up version ("còn bản Plus thì sao?" → Plus).
  - Clarify thiếu model → user trả lời → resolve đúng.
  - MVP 7 capitalization, VF 8 All New trong follow-up.

Run: python tests/test_multi_turn.py
"""

import asyncio
import io
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

PASS = 0
FAIL = 0
ERRORS = []


def report(tid, passed, step, detail):
    global PASS, FAIL, ERRORS
    if passed:
        PASS += 1
        print(f"  [OK]   {tid}: {detail}")
    else:
        FAIL += 1
        ERRORS.append(f"{tid}: {step} — {detail}")
        print(f"  [FAIL] {tid}: {step} — {detail}")


async def _no_llm(query, history):
    return None


def _install_offline_stub():
    import app.agent.nodes.classify as cf

    cf.llm_classify_fallback = _no_llm


# ═══════════════════════════════════════════════════════════════
# Định nghĩa conversations. Mỗi turn: (query, expected)
#   expected: {decision, reason? , model?, version?, topic?}
#   model = None → assert không có model (clarify thiếu model/pronoun)
# ═══════════════════════════════════════════════════════════════
CONVERSATIONS = [
    {
        "name": "Model continuity (no switch)",
        "turns": [
            ("VF 6 có những phiên bản nào?", {"decision": "answer", "model": "VF 6"}),
            ("công suất bao nhiêu?", {"decision": "answer", "model": "VF 6"}),
            ("pin thế nào?", {"decision": "answer", "model": "VF 6"}),
        ],
    },
    {
        "name": "Model switch — memory recency (fix)",
        "turns": [
            ("thông số vf6", {"decision": "answer", "model": "VF 6"}),
            ("vf8 thì sao", {"decision": "answer", "model": "VF 8"}),
            # follow-up không nhắc model → phải dùng VF 8 (mới nhất), KHÔNG phải VF 6
            ("pin xe bao nhiêu", {"decision": "answer", "model": "VF 8"}),
        ],
    },
    {
        "name": "Switch back to earlier model",
        "turns": [
            ("thông số vf6", {"decision": "answer", "model": "VF 6"}),
            ("vf8 thì sao", {"decision": "answer", "model": "VF 8"}),
            ("còn vf6 thì sao", {"decision": "answer", "model": "VF 6"}),
            ("giá bao nhiêu", {"decision": "answer", "model": "VF 6"}),
        ],
    },
    {
        "name": "Version follow-up",
        "turns": [
            ("VF 8 đi được bao xa?", {"decision": "answer", "model": "VF 8"}),
            ("còn bản Plus thì sao?", {"decision": "answer", "model": "VF 8", "version": "Plus"}),
        ],
    },
    {
        "name": "Clarify (missing model) → resolve",
        "turns": [
            ("Xe có HUD không?", {"decision": "clarify", "reason": "missing_model", "model": None}),
            ("VF 6 Eco.", {"decision": "answer", "model": "VF 6", "version": "Eco"}),
            ("vậy Plus thì sao?", {"decision": "answer", "model": "VF 6", "version": "Plus"}),
        ],
    },
    {
        "name": "Pronoun with clear context",
        "turns": [
            ("VF 6 có HUD không?", {"decision": "answer", "model": "VF 6"}),
            ("nó có sưởi ghế không?", {"decision": "answer", "model": "VF 6"}),
        ],
    },
    {
        "name": "Bare model hop across brands",
        "turns": [
            ("VF 8 có mấy túi khí?", {"decision": "answer", "model": "VF 8"}),
            ("còn VF 9?", {"decision": "answer", "model": "VF 9"}),
            ("và VF MPV 7?", {"decision": "answer", "model": "VF MPV 7"}),
            ("thế VF 8 Eco?", {"decision": "answer", "model": "VF 8", "version": "Eco"}),
        ],
    },
    {
        "name": "Broad → topic follow-up (retain model)",
        "turns": [
            ("cho tôi biết về VF 6", {"decision": "clarify", "reason": "missing_topic", "model": "VF 6"}),
            ("kích thước xe", {"decision": "answer", "model": "VF 6"}),
            ("còn trọng lượng?", {"decision": "answer", "model": "VF 6"}),
        ],
    },
    {
        "name": "Switch to VF 8 All New",
        "turns": [
            ("thông số vf6", {"decision": "answer", "model": "VF 6"}),
            ("vf8 thế hệ mới thì sao", {"decision": "answer", "model": "VF 8 All New"}),
            ("pin bao nhiêu", {"decision": "answer", "model": "VF 8 All New"}),
        ],
    },
]


async def main():
    from app.agent.classifier import normalize_model
    from app.agent.nodes.classify import classify_node

    print("╔═══════════════════════════════════════════════════╗")
    print("║         VIVU MULTI-TURN MEMORY TESTS              ║")
    print("╚═══════════════════════════════════════════════════╝\n")

    t0 = time.time()
    _install_offline_stub()

    for conv in CONVERSATIONS:
        print(f"── {conv['name']} ──")
        history = []
        for turn_idx, (query, exp) in enumerate(conv["turns"], 1):
            st = await classify_node({"query": query, "history": history})
            ents = st.get("entities", {})
            got_decision = st.get("decision")
            got_reason = st.get("reason_code") or ""
            got_model = ents.get("model_code")
            got_version = ents.get("version")

            # decision
            ok = got_decision == exp["decision"]
            detail = f"turn{turn_idx} {query!r}: dec={got_decision} (exp {exp['decision']})"

            # reason (clarify)
            if ok and exp.get("reason"):
                if exp["reason"] not in got_reason:
                    ok = False
                    detail += f", reason={got_reason} (exp {exp['reason']})"

            # model
            exp_model = exp.get("model")
            if ok:
                exp_model_norm = normalize_model(exp_model) if exp_model else None
                got_model_norm = normalize_model(got_model) if got_model else None
                actual_none = not got_model
                if exp_model is None:
                    model_ok = actual_none
                else:
                    model_ok = (not actual_none) and got_model_norm == exp_model_norm
                if not model_ok:
                    ok = False
                    detail += f", model={got_model} (exp {exp_model})"

            # version
            if ok and exp.get("version") is not None:
                if got_version != exp["version"]:
                    ok = False
                    detail += f", version={got_version} (exp {exp['version']})"

            report(f"MT-{conv['name'].replace(' ', '')[:12]}-T{turn_idx}", ok, "classify", detail)

            # build history (assistant placeholder — model/version đến từ user turn)
            history.append({"role": "user", "content": query})
            history.append({"role": "assistant", "content": "(assistant)"})

    elapsed = time.time() - t0
    total = PASS + FAIL
    print(f"\n{'═' * 52}")
    print(f"  RESULTS: {PASS}/{total} PASS, {FAIL} FAIL ({elapsed:.1f}s)")
    print(f"{'═' * 52}")
    if ERRORS:
        print(f"\n{FAIL} FAILURES:")
        for e in ERRORS:
            print(f"  ✗ {e}")
    return FAIL


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
