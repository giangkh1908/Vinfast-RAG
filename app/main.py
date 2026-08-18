import logging

from app.tracing import setup_tracing

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api.chat import router as chat_router
from app.api.health import router as health_router
from app.api.metrics import router as metrics_router
from app.api.admin_prompts import router as admin_prompts_router
from app.core.rate_limit import setup_rate_limiting
from app.core.db import pool_stats

# Configure logging so bds.* loggers appear in terminal
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logging.getLogger("bds").setLevel(logging.INFO)

app = FastAPI(title="Vivu Chatbot Backend API", version="1.0.0")

# CORS Middleware (Cho phép frontend từ Vercel/Netlify/Localhost kết nối)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Rate limiting + backpressure middleware
setup_rate_limiting(app)

app.include_router(health_router)
app.include_router(chat_router)
app.include_router(metrics_router)
app.include_router(admin_prompts_router)

# Mount StaticFiles nếu có folder static (nếu chạy pure API thì bỏ qua)
static_dir = Path("app/static")
if static_dir.exists() and (static_dir / "index.html").exists():
    app.mount("/", StaticFiles(directory="app/static", html=True))

setup_tracing()


@app.on_event("startup")
async def _prewarm():
    """Warm cache system prompt + tool schemas + telemetry + prompt registry để request đầu không trả
    ~2s PG cold-load giữa stream."""
    try:
        from app.agent.prompts import get_system_prompt
        from app.agent.schemas import build_tool_schemas
        from app.core.db import get_pool
        from app.core.telemetry import ensure_telemetry_schema
        from app.core.prompt_manager import prompt_manager
        # Pre-warm pool: tạo min_size connections ngay
        await get_pool()
        await ensure_telemetry_schema()
        await prompt_manager.ensure_schema()
        await get_system_prompt()
        await build_tool_schemas()
        logging.getLogger("bds").info("Prewarm OK: pool + telemetry + prompt registry + system prompt + tool schemas")
    except Exception as e:
        logging.getLogger("bds").warning("Prewarm failed (sẽ lazy-load): %s", e)

