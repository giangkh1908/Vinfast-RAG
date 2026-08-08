from app.tracing import setup_tracing

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.api.chat import router as chat_router

app = FastAPI(title="Vivu Chatbot")
app.include_router(chat_router)
app.mount("/", StaticFiles(directory="app/static", html=True))
setup_tracing()
