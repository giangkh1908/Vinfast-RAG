import logging

from app.tracing import setup_tracing

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.api.chat import router as chat_router

# Configure logging so bds.* loggers appear in terminal
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logging.getLogger("bds").setLevel(logging.INFO)

app = FastAPI(title="Vivu Chatbot")
app.include_router(chat_router)
app.mount("/", StaticFiles(directory="app/static", html=True))
setup_tracing()
