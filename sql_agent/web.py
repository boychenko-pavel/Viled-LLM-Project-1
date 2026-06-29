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
from sql_agent.currency import CurrencyTool
from sql_agent.forecast import SalesForecastTool
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


class CurrencyCurrentRow(BaseModel):
    currency: str
    viled_inform: str | int | float | None = ""


class CurrencyCurrentRequest(BaseModel):
    values: dict[str, str | int | float | None]


class CurrencyCurrentResponse(BaseModel):
    message: str
    saved_count: int


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


AGENT_WORKSPACES = {
    "bi_analytics": {
        "name": "SQL Analytic",
        "description": "SQL Server analytics agent",
        "type": "agent",
    },
    "office_manager": {
        "name": "Office Manager",
        "description": "General LLM assistant",
        "type": "agent",
    },
    "hr": {
        "name": "HR",
        "description": "Bonus policy RAG assistant",
        "type": "agent",
    },
}

TOOL_WORKSPACES = {
    "forecast_sales": {
        "name": "Forecast Sales",
        "description": "Monthly SQL sales forecast",
        "type": "tool",
    },
    "currency": {
        "name": "Currency",
        "description": "mig.kz currency table parser",
        "type": "tool",
    },
}

OFFICE_MEMORY_FILE = MEMORY_DIR / "office_manager_memory.json"
OFFICE_MANAGER_FIXED_ANSWERS = {
    "любит ли меня леська": "Да, больше всего на свете она любит тебя и своих срадких котиков",
}


def _validate_workspace(workspace: str) -> str:
    if workspace not in WORKSPACES:
        raise HTTPException(status_code=404, detail=f"Unknown workspace: {workspace}")
    return workspace


WORKSPACES = {**AGENT_WORKSPACES, **TOOL_WORKSPACES}


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
            fixed_answer = self._fixed_answer(cleaned_message)
            if fixed_answer is not None:
                memory.add_turn(cleaned_message, fixed_answer)
                self.memory_repository.save(memory)
                return fixed_answer

            prompt = self._build_prompt(memory, cleaned_message)
            response = build_llm().invoke(prompt)
            answer = getattr(response, "content", response)
            if isinstance(answer, list):
                answer = "\n".join(str(item) for item in answer)
            answer = str(answer).strip()
            memory.add_turn(cleaned_message, answer)
            self.memory_repository.save(memory)
            return answer

    def _fixed_answer(self, message: str) -> str | None:
        normalized = message.casefold().strip()
        normalized = normalized.rstrip(" ?!.,;:")
        return OFFICE_MANAGER_FIXED_ANSWERS.get(normalized)

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
    "hr": HrAgent(),
}
tools = {
    "forecast_sales": SalesForecastTool(),
    "currency": CurrencyTool(),
}
app = FastAPI(title="Viled ATLAS LLM Project", version="1.0.0")
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
    if workspace in tools:
        return MemoryResponse(conversation=tools[workspace].load_conversation())
    return MemoryResponse(conversation=agents[workspace].load_conversation())


@app.post("/api/chat", response_model=ChatResponse)
def chat(request: ChatRequest) -> ChatResponse:
    workspace = _validate_workspace(request.workspace)
    try:
        if workspace in tools:
            answer = tools[workspace].ask(request.message)
        else:
            answer = agents[workspace].ask(request.message)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except OperationalError as exc:
        raise HTTPException(
            status_code=503,
            detail="SQL Server недоступен, проверьте VPN/сеть",
        ) from exc
    except DBAPIError as exc:
        raise HTTPException(
            status_code=500,
            detail="Ошибка выполнения SQL-запроса. Проверьте имя таблицы, колонки и права доступа.",
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


@app.post("/api/currency/viled-inform", response_model=ChatResponse)
def currency_viled_inform() -> ChatResponse:
    tool = tools["currency"]
    if not isinstance(tool, CurrencyTool):
        raise HTTPException(status_code=500, detail="Currency tool is not available.")

    try:
        return ChatResponse(answer=tool.ask("snapshot"))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Currency request failed: {exc}") from exc


@app.get("/api/currency/viled-inform/current", response_model=list[CurrencyCurrentRow])
def currency_viled_inform_current() -> list[CurrencyCurrentRow]:
    tool = tools["currency"]
    if not isinstance(tool, CurrencyTool):
        raise HTTPException(status_code=500, detail="Currency tool is not available.")

    try:
        return [CurrencyCurrentRow(**row) for row in tool.load_current_viled_inform_form()]
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Currency current form failed: {exc}") from exc


@app.post("/api/currency/viled-inform/current", response_model=CurrencyCurrentResponse)
def save_currency_viled_inform_current(
    request: CurrencyCurrentRequest,
) -> CurrencyCurrentResponse:
    tool = tools["currency"]
    if not isinstance(tool, CurrencyTool):
        raise HTTPException(status_code=500, detail="Currency tool is not available.")

    try:
        saved_count = tool.save_current_viled_inform(request.values)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Currency current save failed: {exc}") from exc

    return CurrencyCurrentResponse(
        message=f"Saved {saved_count} Viled Inform value(s).",
        saved_count=saved_count,
    )


@app.post("/api/memory/reset", response_model=ChatResponse)
def reset_memory(workspace: str = "bi_analytics") -> ChatResponse:
    workspace = _validate_workspace(workspace)
    if workspace in tools:
        return ChatResponse(answer=tools[workspace].reset_memory())
    return ChatResponse(answer=agents[workspace].reset_memory())


@app.get("/api/forecast-sales/chart", response_model=ChartResponse)
def forecast_sales_chart() -> ChartResponse:
    try:
        tool = tools["forecast_sales"]
        if not isinstance(tool, SalesForecastTool):
            raise RuntimeError("Forecast Sales tool is not available.")
        return ChartResponse(image_data=tool.build_matplotlib_chart_data_uri())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except OperationalError as exc:
        raise HTTPException(
            status_code=503,
            detail="SQL Server недоступен, проверьте VPN/сеть",
        ) from exc
    except DBAPIError as exc:
        raise HTTPException(
            status_code=500,
            detail="Ошибка выполнения SQL-запроса прогноза. Проверьте таблицу [LLM].[sales], колонки и права доступа.",
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
