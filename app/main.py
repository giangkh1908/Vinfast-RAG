import logging
import time
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api.admin_prompts import router as admin_prompts_router
from app.api.chat import router as chat_router
from app.api.health import router as health_router
from app.api.metrics import router as metrics_router
from app.api.prometheus import router as prometheus_router
from app.config import settings
from app.core.exceptions import AppError
from app.core.logging_config import clear_request_context, set_request_context, setup_logging
from app.core.security.rate_limit import setup_rate_limiting

# Structured logging: text (dev) hoặc json (ELK/Loki/Grafana) tuỳ LOG_FORMAT
setup_logging(settings.log_format)
logging.getLogger("bds").setLevel(logging.INFO)

app = FastAPI(title="Vivu Chatbot Backend API", version="1.0.0")


@app.middleware("http")
async def _request_context(request, call_next):
    """Gán request_id (+ session_id nếu có) cho mọi log trong 1 request + ghi Prometheus metric."""
    session_id = request.headers.get("x-session-id") or request.query_params.get("session_id")
    set_request_context(session_id=session_id)
    start = time.perf_counter()
    try:
        response = await call_next(request)
        try:
            from app.core.telemetry.prometheus import record_http

            record_http(method=request.method, path=request.url.path, duration_s=time.perf_counter() - start)
        except Exception:
            pass
        return response
    finally:
        clear_request_context()


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

# ── Global Exception Handlers ────────────────────────────────────────────────


@app.exception_handler(AppError)
async def app_error_handler(request: Request, exc: AppError):
    logging.getLogger("bds.error").warning("AppError on %s: %s (code=%s)", request.url.path, exc.message, exc.code)
    return JSONResponse(status_code=exc.status_code, content=exc.to_dict())


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": exc.detail if isinstance(exc.detail, str) else str(exc.detail),
            "code": "HTTP_ERROR",
            "status_code": exc.status_code,
            "detail": exc.detail,
        },
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    logging.getLogger("bds.error").exception("Unhandled server error on %s: %s", request.url.path, exc)
    return JSONResponse(
        status_code=500,
        content={
            "error": "Đã xảy ra lỗi hệ thống. Vui lòng thử lại sau.",
            "code": "INTERNAL_SERVER_ERROR",
            "status_code": 500,
            "detail": "Internal server error",
        },
    )


app.include_router(health_router)
app.include_router(chat_router)
app.include_router(metrics_router)
app.include_router(admin_prompts_router)
app.include_router(prometheus_router)

# Mount StaticFiles nếu có folder static (nếu chạy pure API thì bỏ qua)
static_dir = Path("app/static")
if static_dir.exists() and (static_dir / "index.html").exists():
    app.mount("/", StaticFiles(directory="app/static", html=True))


@app.on_event("startup")
async def _prewarm():
    """Warm cache system prompt + tool schemas + telemetry + prompt registry để request đầu không trả
    ~2s PG cold-load giữa stream."""
    try:
        from app.agent.prompts import get_system_prompt
        from app.agent.schemas import build_tool_schemas
        from app.core.rag.prompt_manager import prompt_manager
        from app.core.storage.db import get_pool
        from app.core.telemetry.telemetry import ensure_telemetry_schema

        # Pre-warm pool: tạo min_size connections ngay
        await get_pool()
        await ensure_telemetry_schema()
        await prompt_manager.ensure_schema()
        await get_system_prompt()
        await build_tool_schemas()

        # Khởi động Kafka Producer & Consumer Worker ngầm
        from app.core.telemetry.kafka_producer import KafkaProducerService
        from app.workers.kafka_worker import start_kafka_worker_background

        await KafkaProducerService.get_instance()
        await start_kafka_worker_background()

        logging.getLogger("bds").info(
            "Prewarm OK: pool + telemetry + Kafka + prompt registry + system prompt + tool schemas"
        )
    except Exception as e:
        logging.getLogger("bds").warning("Prewarm failed (sẽ lazy-load): %s", e)


@app.on_event("shutdown")
async def _shutdown():
    try:
        from app.core.telemetry.kafka_producer import KafkaProducerService
        from app.workers.kafka_worker import stop_kafka_worker_background

        stop_kafka_worker_background()
        producer = await KafkaProducerService.get_instance()
        await producer.stop()
        logging.getLogger("bds").info("Kafka Producer and Worker shutdown cleanly.")
    except Exception:
        pass
