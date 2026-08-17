# Vivu — Agentic RAG Architecture

## Hệ thống tổng quan

```mermaid
flowchart LR
    subgraph User
        U[Khách hàng]
    end

    subgraph Agent["Agent (hybrid intent + deterministic plan)"]
        direction TB
        CLS[Classify<br/>rule intent + entity] -->|thiếu model| ASK[Hỏi lại clarify]
        CLS -->|intent rõ| PLAN[build_tool_plan<br/>deterministic]
        CLS -.LLM fallback strict-JSON.-> CLS
        PLAN --> EXEC[Execute plan song song<br/>asyncio.gather]
        EXEC --> SYN[Generate — LLM tổng hợp]
        SYN --> GND[Groundedness<br/>validate citations]
        GND -->|pass| RESP[Response]
        GND -->|refuse thuần| RESP2[Response không nguồn]
    end

    subgraph Memory["Multi-turn memory"]
        direction TB
        SESS[chat_sessions (PG)<br/>summary + turn_count]
        WIN[Window 7 turn<br/>sanitize history]
    end

    subgraph Tools["Tools"]
        direction TB
        T1[get_price]
        T2[get_specs keys/category]
        T3[search_knowledge_base]
        T4[list_available_models]
        T5[get_colors]
        T6[get_active_promotions]
        T7[link tools x5]
    end

    subgraph Data["Data Sources"]
        direction TB
        PG[(PostgreSQL<br/>car_specs, price, colors...)]
        QD[(Qdrant<br/>hybrid search 3 collection)]
    end

    subgraph Pipeline["Data Pipeline"]
        direction TB
        API[omapi.vinfastauto.com<br/>car catalog]
        JSON[model_specs.json<br/>3659 dòng specs]
        MD[data/*.md<br/>promotions, maintenance]
        EMBED[chunk → embed → Qdrant]
    end

    U -->|SSE streaming| Agent
    Agent --> Memory
    RESP --> U
    Tools --> Data
    Pipeline --> Data
```    Agent --> Tools
    Tools --> Data
    Pipeline --> Data
```

## Data Flow

```mermaid
flowchart LR
    subgraph Input["Nguồn data"]
        A1[API carModel]
        A2[model_specs.json]
        A3[Promotion .md files]
        A4[Maintenance links]
        A5[Policy pages]
        A6[Brochure PDFs]
    end

    subgraph DB["PostgreSQL"]
        T1[(car_catalog<br/>15 models)]
        T2[(car_pricing<br/>giá + promo)]
        T3[(car_specs<br/>thông số KT)]
        T4[(promotion)]
        T5[(maintenance_link<br/>24 links)]
        T6[(utility_link<br/>6 links)]
        T7[(user_memory)]
    end

    subgraph VDB["Qdrant"]
        Q1[(vinfast_kb<br/>dense + sparse)]
    end

    A1 --> T1
    A2 --> T3
    A2 --> T2
    A3 --> T4
    A4 --> T5
    A5 --> Q1
    A6 --> Q1
```

## 3 Dev Split

```mermaid
flowchart LR
    subgraph D1["Dev 1 — Agent"]
        B1[11 Tools]
        B2[Agent Loop]
        B3[Classifier]
        B4[Grounding]
        B5[Prompts]
    end

    subgraph D2["Dev 2 — Data"]
        A1[DB Schema 8 bảng]
        A2[Seed scripts]
        A3[Firecrawl + Embed]
        A4[Qdrant setup]
        A5[Cron jobs]
    end

    subgraph D3["Dev 3 — App"]
        C1[FastAPI shell]
        C2[Chat UI + SSE]
        C3[Config + Core]
    end

    D2 -->|DB ready| D1
    D2 -->|DB ready| D3
    D1 -->|Agent ready| D3
```

## Module map (thêm từ 8/2026)

| Module | Vai trò | Doc chi tiết |
|---|---|---|
| `app/agent/intent.py` | Hybrid intent (12 intent) + spec_category/spec_key maps + LLM fallback strict-JSON | `docs/INTENT_PLANNING.md` |
| `app/agent/direct_plan.py` | `build_tool_plan` — intent → tool calls deterministic | `docs/INTENT_PLANNING.md` |
| `app/agent/nodes/classify.py` | Rule entity + topic + hybrid intent; clarify đúng lúc | `docs/INTENT_PLANNING.md` |
| `app/agent/history.py` | Sanitize history (chống injection, window 7 turn) | `docs/MEMORY_PLAN.md` |
| `app/core/session_store.py` | `chat_sessions` (summary, turn_count) + summarize | `docs/MEMORY_PLAN.md` |
| `app/agent/nodes/summarize.py` | Running summary mỗi 7 turn | `docs/MEMORY_PLAN.md` |
| `app/agent/llm.py` | Token limits (input 1000 reject / output 4000), `truncate_messages`, `get_llm` | `docs/MEMORY_PLAN.md` |
| `frontend/` | React+TS chat (SSE, StatusBar, markdown, localStorage session) | `docs/FRONTEND_PLAN.md` |

## Agent Loop chi tiết

```mermaid
flowchart TD
    Q[User query] --> GATE{Validate}
    GATE -->|session_id sai / >1000 token| REJECT[HTTP 400]
    GATE -->|ok| SAN[Sanitize history<br/>chống injection]
    SAN --> CLS{Classify: rule intent}

    CLS -->|thiếu model cần thiết| CLARIFY[clarify]
    CLS -->|intent rõ| PLAN[build_tool_plan<br/>deterministic]
    CLS -.LLM fallback strict-JSON.-> CLS

    PLAN --> EXEC[Execute plan song song<br/>asyncio.gather]
    EXEC --> CTX[Build context + summary]
    CTX --> SYN[Synthesize — LLM generate]
    SYN --> VLD[Validate citations]
    VLD -->|ok| DONE[Stream response + sources]
    VLD -->|refuse thuần| DONE2[Stream response không nguồn]

    DONE --> MEM[Upsert session: turn_count+1]
    MEM --> SUM{Turn % 7 == 0?}
    SUM -->|yes| SUMM[Summarize → update_summary DB]
```

## Tool Routing

```mermaid
flowchart LR
    Q[Query] --> I{Intent rules}
    I -->|price| T1[get_price]
    I -->|spec_query| T2[get_specs category/keys]
    I -->|feature_presence| T3[get_specs version=None + keys]
    I -->|cross_model_feature| T4[get_specs x9 model]
    I -->|compare| T5[get_specs x models + price]
    I -->|versions_list| T6[get_price]
    I -->|models_list| T7[list_available_models]
    I -->|colors| T8[get_colors]
    I -->|utility| T9[link tools theo subtype]
    I -->|policy| T10[search_knowledge_base]
    I -->|general| T11[search_knowledge_base + LLM fallback]
    I -->|out_of_scope| REF[Respond không tool]
```
