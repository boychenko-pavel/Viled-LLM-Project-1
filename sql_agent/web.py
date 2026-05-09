from __future__ import annotations

from pathlib import Path
from threading import Lock

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy.exc import DBAPIError, OperationalError

from sql_agent.config import LM_STUDIO_BASE_URL, LM_STUDIO_MODEL, MEMORY_FILE
from sql_agent.service import SqlAgentService


STATIC_DIR = Path(__file__).resolve().parent.parent / "web" / "static"


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=4000)


class ChatResponse(BaseModel):
    answer: str


class MemoryResponse(BaseModel):
    conversation: list[dict[str, str]]


class StatusResponse(BaseModel):
    model: str
    llm_base_url: str
    memory_file: str


class WebSqlAgent:
    def __init__(self) -> None:
        self.service = SqlAgentService()
        self._lock = Lock()

    def ask(self, message: str) -> str:
        cleaned_message = message.strip()
        if not cleaned_message:
            raise ValueError("Message is empty.")

        # Agent memory is file-backed, so serialize web requests to keep chat history coherent.
        with self._lock:
            return self.service.ask_database(cleaned_message)

    def load_conversation(self) -> list[dict[str, str]]:
        return self.service.memory_repository.load().conversation

    def reset_memory(self) -> str:
        with self._lock:
            return self.service.reset_memory()


agent = WebSqlAgent()
app = FastAPI(title="Viled SQL Agent Web", version="1.0.0")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/status", response_model=StatusResponse)
def status() -> StatusResponse:
    return StatusResponse(
        model=LM_STUDIO_MODEL,
        llm_base_url=LM_STUDIO_BASE_URL,
        memory_file=str(MEMORY_FILE),
    )


@app.get("/api/memory", response_model=MemoryResponse)
def memory() -> MemoryResponse:
    return MemoryResponse(conversation=agent.load_conversation())


@app.post("/api/chat", response_model=ChatResponse)
def chat(request: ChatRequest) -> ChatResponse:
    try:
        answer = agent.ask(request.message)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except (OperationalError, DBAPIError) as exc:
        raise HTTPException(
            status_code=503,
            detail="SQL Server недоступен, проверьте VPN/сеть",
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=(
                "Agent request failed. Check SQL credentials, database access, "
                "ODBC/pymssql drivers, and the local LLM server."
            ),
        ) from exc

    return ChatResponse(answer=answer)


@app.post("/api/memory/reset", response_model=ChatResponse)
def reset_memory() -> ChatResponse:
    return ChatResponse(answer=agent.reset_memory())
