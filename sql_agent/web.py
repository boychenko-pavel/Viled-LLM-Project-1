from __future__ import annotations

from pathlib import Path
import shutil
from threading import Lock

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy.exc import DBAPIError, OperationalError

from sql_agent.config import LM_STUDIO_BASE_URL, LM_STUDIO_MODEL, MEMORY_DIR, MEMORY_FILE
from sql_agent.forecast import SalesForecastAgent
from sql_agent.hr import HR_MEMORY_DIR, HrAgent
from sql_agent.langchain_factory import build_llm
from sql_agent.memory import SqlAgentMemory, SqlAgentMemoryRepository
from sql_agent.service import SqlAgentService


STATIC_DIR = Path(__file__).resolve().parent.parent / "web" / "static"


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=4000)
    workspace: str = Field("bi_analytics", min_length=1, max_length=64)


class ChatResponse(BaseModel):
    answer: str


class ChartResponse(BaseModel):
    image_data: str


class UploadResponse(BaseModel):
    message: str


class HrDocumentResponse(BaseModel):
    source: str
    chunk_count: int
    pages: list[int]
    page_count: int


class HrChunkResponse(BaseModel):
    id: str
    source: str
    page: int | None = None
    chunk_index: int | None = None
    distance: float | None = None
    text: str


class MemoryResponse(BaseModel):
    conversation: list[dict[str, str]]


class StatusResponse(BaseModel):
    model: str
    llm_base_url: str
    memory_file: str
    workspaces: list[dict[str, str]]


WORKSPACES = {
    "bi_analytics": {
        "name": "SQL Analytic",
        "description": "SQL Server analytics agent",
    },
    "office_manager": {
        "name": "Office Manager",
        "description": "General LLM assistant",
    },
    "forecast_sales": {
        "name": "Forecast Sales",
        "description": "Monthly SQL sales forecast",
    },
    "hr": {
        "name": "HR",
        "description": "Bonus policy RAG assistant",
    },
}

OFFICE_MEMORY_FILE = MEMORY_DIR / "office_manager_memory.json"


def _validate_workspace(workspace: str) -> str:
    if workspace not in WORKSPACES:
        raise HTTPException(status_code=404, detail=f"Unknown workspace: {workspace}")
    return workspace


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


class OfficeManagerAgent:
    def __init__(self) -> None:
        self.memory_repository = SqlAgentMemoryRepository(OFFICE_MEMORY_FILE)
        self._lock = Lock()

    def ask(self, message: str) -> str:
        cleaned_message = message.strip()
        if not cleaned_message:
            raise ValueError("Message is empty.")

        with self._lock:
            memory = self.memory_repository.load()
            prompt = self._build_prompt(memory, cleaned_message)
            response = build_llm().invoke(prompt)
            answer = getattr(response, "content", response)
            if isinstance(answer, list):
                answer = "\n".join(str(item) for item in answer)
            answer = str(answer).strip()
            memory.add_turn(cleaned_message, answer)
            self.memory_repository.save(memory)
            return answer

    def load_conversation(self) -> list[dict[str, str]]:
        return self.memory_repository.load().conversation

    def reset_memory(self) -> str:
        with self._lock:
            self.memory_repository.save(SqlAgentMemory())
            return "Office Manager memory cleared."

    def _build_prompt(self, memory: SqlAgentMemory, message: str) -> str:
        history_lines = []
        for item in memory.conversation[-12:]:
            role = item.get("role", "user").upper()
            content = item.get("content", "")
            history_lines.append(f"{role}: {content}")
        history = "\n".join(history_lines) if history_lines else "No prior conversation."
        return (
            "You are Office Manager, a helpful general office assistant. "
            "Answer in Russian unless the user asks otherwise. "
            "Help with writing, summaries, planning, emails, documents, and general questions. "
            "You do not have SQL/database tools in this workspace.\n\n"
            f"Conversation history:\n{history}\n\n"
            f"Current user message:\n{message}"
        )


agents = {
    "bi_analytics": WebSqlAgent(),
    "office_manager": OfficeManagerAgent(),
    "forecast_sales": SalesForecastAgent(),
    "hr": HrAgent(),
}
app = FastAPI(title="VILED ATLAS", version="1.0.0")
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
        workspaces=[
            {"id": workspace_id, **workspace}
            for workspace_id, workspace in WORKSPACES.items()
        ],
    )


@app.get("/api/memory", response_model=MemoryResponse)
def memory(workspace: str = "bi_analytics") -> MemoryResponse:
    workspace = _validate_workspace(workspace)
    return MemoryResponse(conversation=agents[workspace].load_conversation())


@app.post("/api/chat", response_model=ChatResponse)
def chat(request: ChatRequest) -> ChatResponse:
    workspace = _validate_workspace(request.workspace)
    try:
        answer = agents[workspace].ask(request.message)
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
def reset_memory(workspace: str = "bi_analytics") -> ChatResponse:
    workspace = _validate_workspace(workspace)
    return ChatResponse(answer=agents[workspace].reset_memory())


@app.get("/api/forecast-sales/chart", response_model=ChartResponse)
def forecast_sales_chart() -> ChartResponse:
    try:
        agent = agents["forecast_sales"]
        if not isinstance(agent, SalesForecastAgent):
            raise RuntimeError("Forecast Sales agent is not available.")
        return ChartResponse(image_data=agent.build_matplotlib_chart_data_uri())
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
            detail="Failed to build detailed Matplotlib forecast chart.",
        ) from exc


@app.post("/api/hr/documents", response_model=UploadResponse)
def upload_hr_document(file: UploadFile = File(...)) -> UploadResponse:
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Upload a PDF file.")

    upload_dir = HR_MEMORY_DIR / "uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)
    temp_path = upload_dir / Path(file.filename).name
    try:
        with temp_path.open("wb") as output:
            shutil.copyfileobj(file.file, output)
        agent = agents["hr"]
        if not isinstance(agent, HrAgent):
            raise RuntimeError("HR agent is not available.")
        return UploadResponse(message=agent.ingest_pdf(temp_path))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail="Failed to process HR PDF document.") from exc
    finally:
        temp_path.unlink(missing_ok=True)


@app.get("/api/hr/documents", response_model=list[HrDocumentResponse])
def hr_documents() -> list[HrDocumentResponse]:
    agent = agents["hr"]
    if not isinstance(agent, HrAgent):
        raise HTTPException(status_code=500, detail="HR agent is not available.")
    return [HrDocumentResponse(**item) for item in agent.list_documents()]


@app.get("/api/hr/chunks", response_model=list[HrChunkResponse])
def hr_chunks(source: str | None = None, limit: int = 100) -> list[HrChunkResponse]:
    agent = agents["hr"]
    if not isinstance(agent, HrAgent):
        raise HTTPException(status_code=500, detail="HR agent is not available.")
    return [HrChunkResponse(**item) for item in agent.list_chunks(source=source, limit=limit)]


@app.get("/api/hr/search", response_model=list[HrChunkResponse])
def hr_search(q: str, limit: int = 10) -> list[HrChunkResponse]:
    agent = agents["hr"]
    if not isinstance(agent, HrAgent):
        raise HTTPException(status_code=500, detail="HR agent is not available.")
    try:
        return [HrChunkResponse(**item) for item in agent.search_memory(query=q, limit=limit)]
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
