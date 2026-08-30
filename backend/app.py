import os
import uuid

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel

from config import require_tokens
from agent import handle_query
from data_sync import sync_and_normalize, get_data_quality_report

app = FastAPI(title="Skylark BI Agent")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# In-memory session store: session_id -> Anthropic-format message history.
# Fine for a demo/hosted prototype; resets on server restart (documented in README).
SESSIONS: dict[str, list] = {}
MAX_HISTORY_MESSAGES = 20


class ChatRequest(BaseModel):
    session_id: str | None = None
    message: str


class ChatResponse(BaseModel):
    session_id: str
    reply: str
    tool_log: list


@app.on_event("startup")
def _startup():
    try:
        require_tokens()
        sync_and_normalize(force_refresh=True)
        print("[startup] Initial monday.com sync succeeded.")
    except Exception as e:
        print(f"[startup] Skipped initial sync ({e}). Will try again on first query.")


@app.post("/api/chat", response_model=ChatResponse)
def chat(req: ChatRequest):
    if not req.message or not req.message.strip():
        raise HTTPException(status_code=400, detail="message must not be empty")
    try:
        require_tokens()
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))

    session_id = req.session_id or str(uuid.uuid4())
    history = SESSIONS.get(session_id, [])
    try:
        reply, updated_history, tool_log = handle_query(history, req.message)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Agent error: {e}")

    SESSIONS[session_id] = updated_history[-MAX_HISTORY_MESSAGES:]
    return ChatResponse(session_id=session_id, reply=reply, tool_log=tool_log)


@app.post("/api/refresh")
def refresh():
    try:
        sync_and_normalize(force_refresh=True)
        return {"status": "ok", "data_quality": get_data_quality_report()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/health")
def health():
    return {"status": "ok"}


FRONTEND_INDEX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "frontend", "index.html")


@app.get("/")
def root():
    if os.path.exists(FRONTEND_INDEX):
        return FileResponse(FRONTEND_INDEX)
    return {"status": "backend running, frontend/index.html not found"}
