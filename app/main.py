import logging

from app.tracing import setup_tracing

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api.chat import router as chat_router
from app.core.rate_limit import setup_rate_limiting
from app.core.db import pool_stats

# Configure logging so bds.* loggers appear in terminal
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logging.getLogger("bds").setLevel(logging.INFO)

app = FastAPI(title="Vivu Chatbot Backend API")

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

app.include_router(chat_router)

# Mount StaticFiles nếu có folder static (nếu chạy pure API thì bỏ qua)
static_dir = Path("app/static")
if static_dir.exists() and (static_dir / "index.html").exists():
    app.mount("/", StaticFiles(directory="app/static", html=True))

setup_tracing()


@app.get("/api/health")
async def health():
    """Health check + pool stats for monitoring."""
    stats = pool_stats()
    return JSONResponse(content={"status": "ok", "pool": stats})


@app.on_event("startup")
async def _prewarm():
    """Warm cache system prompt + tool schemas để request đầu không trả
    ~2s PG cold-load giữa stream."""
    try:
        from app.agent.prompts import get_system_prompt
        from app.agent.schemas import build_tool_schemas
        from app.core.db import get_pool
        # Pre-warm pool: tạo min_size connections ngay
        await get_pool()
        await get_system_prompt()
        await build_tool_schemas()
        logging.getLogger("bds").info("Prewarm OK: pool + system prompt + tool schemas")
    except Exception as e:
        logging.getLogger("bds").warning("Prewarm failed (sẽ lazy-load): %s", e)
