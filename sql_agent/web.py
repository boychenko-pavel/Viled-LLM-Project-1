from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from queue import Queue
import shutil
from threading import Lock, Thread
from time import perf_counter
from typing import Iterator, Literal

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy.exc import DBAPIError, OperationalError
from starlette.background import BackgroundTask
from starlette.concurrency import run_in_threadpool

from sql_agent.config import LM_STUDIO_BASE_URL, LM_STUDIO_MODEL, MEMORY_DIR, MEMORY_FILE
from sql_agent.currency import CurrencyTool
from sql_agent.excel_export import export_sql_to_excel
from sql_agent.forecast import SalesForecastTool
from sql_agent.hh_api import HhApiClient, HhApiError, ResumeSearch, VacancySearch
from sql_agent.hr import HR_MEMORY_DIR, HrAgent
from sql_agent.langchain_factory import build_llm
from sql_agent.memory import SqlAgentMemory, SqlAgentMemoryRepository
from sql_agent.office_calendar import (
    CalendarApiError,
    CalendarConfigurationError,
    GoogleCalendarService,
)
from sql_agent.query_utils import format_sql_for_display, format_sql_response
from sql_agent.service import SqlAgentService
from sql_agent.sql_reviewer import (
    OPENAI_GENERATION_SUCCESS_MESSAGE,
    OpenAISqlGenerationError,
    OpenAISqlReviewer,
    OpenAIUnavailableError,
    REVIEW_DISABLED_MESSAGE,
)
from sql_agent.voice_input import (
    VoiceInputError,
    VoiceInputService,
    VoiceInputUnavailableError,
)


STATIC_DIR = Path(__file__).resolve().parent.parent / "web" / "static"


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=20_000)
    workspace: str = Field("bi_analytics", min_length=1, max_length=64)
    sql_calculation_enabled: bool = True
    sql_check_mode_enabled: bool = True
    openai_model: Literal[
        "gpt-5.6",
        "gpt-5.6-sol",
        "gpt-5.6-terra",
        "gpt-5.6-luna",
    ] = "gpt-5.6"
    reasoning_effort: Literal["none", "low", "medium", "high", "xhigh", "max"] = "medium"
    service_tier: Literal["default", "priority"] = "default"


class ChatResponse(BaseModel):
    answer: str


class ExcelExportRequest(BaseModel):
    sql: str | None = Field(None, min_length=1, max_length=200_000)
    message: str | None = Field(None, min_length=1, max_length=20_000)


class ChartResponse(BaseModel):
    image_data: str


class UploadResponse(BaseModel):
    message: str


class VoiceTranscriptionResponse(BaseModel):
    text: str
    language: str | None = None
    duration_seconds: float | None = None


class OfficeTaskCreateRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=300)
    due_at: datetime
    notes: str = Field("", max_length=5000)


class OfficeTaskUpdateRequest(BaseModel):
    completed: bool


class OfficeTaskResponse(BaseModel):
    id: str
    title: str
    notes: str
    due_at: str
    completed: bool
    html_link: str


class OfficeCalendarStatusResponse(BaseModel):
    configured: bool
    calendar_id: str


class CurrencyCurrentRow(BaseModel):
    currency: str
    viled_inform: str | int | float | None = ""


class CurrencyCurrentRequest(BaseModel):
    values: dict[str, str | int | float | None]


class CurrencyCurrentResponse(BaseModel):
    message: str
    saved_count: int


class CurrencyPricingRow(BaseModel):
    date: str
    currency: str
    rate: str


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


class HhAreaResponse(BaseModel):
    id: str
    name: str


class HhVacancySearchRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=3000)
    area: str = Field("40", min_length=1, max_length=32)
    experience: str | None = Field(None, max_length=32)
    salary: int | None = Field(None, ge=0)
    only_with_salary: bool = False
    period: int | None = Field(None, ge=1, le=30)
    order_by: str = Field("publication_time", max_length=32)
    page: int = Field(0, ge=0)
    per_page: int = Field(20, ge=1, le=100)


class HhVacancyResponse(BaseModel):
    id: str
    name: str
    employer: str
    area: str
    experience: str
    salary_from: int | float | None = None
    salary_to: int | float | None = None
    salary_currency: str
    salary_gross: bool | None = None
    published_at: str
    url: str
    snippet_requirement: str
    snippet_responsibility: str


class HhVacancySearchResponse(BaseModel):
    found: int
    page: int
    pages: int
    per_page: int
    items: list[HhVacancyResponse]


class HhResumeSearchRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=3000)
    area: str = Field("40", min_length=1, max_length=32)
    experience: str | None = Field(None, max_length=32)
    salary_from: int | None = Field(None, ge=0)
    salary_to: int | None = Field(None, ge=0)
    only_with_salary: bool = False
    education_level: str | None = Field(None, max_length=32)
    job_search_status: str | None = Field(None, max_length=32)
    period: int | None = Field(None, ge=1, le=30)
    order_by: str = Field("publication_time", max_length=32)
    page: int = Field(0, ge=0)
    per_page: int = Field(20, ge=1, le=100)


class HhResumeResponse(BaseModel):
    id: str
    title: str
    full_name: str
    age: int | None = None
    gender: str
    area: str
    salary_amount: int | float | None = None
    salary_currency: str
    total_experience_months: int | None = None
    education_level: str
    job_search_status: str
    last_position: str
    last_company: str
    updated_at: str
    url: str


class HhResumeSearchResponse(BaseModel):
    found: int
    page: int
    pages: int
    per_page: int
    items: list[HhResumeResponse]


class MemoryResponse(BaseModel):
    conversation: list[dict[str, str]]


class StatusResponse(BaseModel):
    model: str
    openai_model: str
    openai_reasoning_effort: str
    openai_service_tier: str
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


def _agent_error_detail(exc: Exception) -> str:
    if isinstance(exc, ValueError):
        return str(exc)
    if isinstance(exc, OperationalError):
        return "SQL Server недоступен, проверьте VPN/сеть"
    if isinstance(exc, DBAPIError):
        return "Ошибка выполнения SQL-запроса. Проверьте имя таблицы, колонки и права доступа."
    return (
        "Agent request failed. Check SQL credentials, database access, "
        "ODBC/pymssql drivers, and the local LLM server."
    )


WORKSPACES = {**AGENT_WORKSPACES, **TOOL_WORKSPACES}


class WebSqlAgent:
    def __init__(
        self,
        service: SqlAgentService | None = None,
        sql_reviewer: OpenAISqlReviewer | None = None,
    ) -> None:
        self.service = service or SqlAgentService()
        self.sql_reviewer = sql_reviewer or OpenAISqlReviewer()
        self._lock = Lock()

    def ask(self, message: str) -> str:
        cleaned_message = message.strip()
        if not cleaned_message:
            raise ValueError("Message is empty.")

        # Agent memory is file-backed, so serialize web requests to keep chat history coherent.
        with self._lock:
            return self.service.ask_database(cleaned_message)

    def stream(
        self,
        message: str,
        *,
        openai_model: str = "gpt-5.6",
        reasoning_effort: str = "medium",
        service_tier: str = "default",
        sql_calculation_enabled: bool = True,
        sql_check_mode_enabled: bool = True,
    ) -> Iterator[str]:
        cleaned_message = message.strip()
        if not cleaned_message:
            raise ValueError("Message is empty.")

        events: Queue[dict[str, object]] = Queue()
        request_started_at = perf_counter()
        sql_started_at = request_started_at
        result_started_at = request_started_at
        openai_generation_duration = 0.0

        def emit_local_sql(sql: str) -> None:
            nonlocal result_started_at
            sql_ready_at = perf_counter()
            events.put(
                {
                    "event": "sql",
                    "sql": format_sql_for_display(sql),
                    "duration_seconds": sql_ready_at - sql_started_at,
                }
            )
            review_started_at = perf_counter()
            if sql_check_mode_enabled:
                review = self.sql_reviewer.review(
                    cleaned_message,
                    sql,
                    model=openai_model,
                    reasoning_effort=reasoning_effort,
                    service_tier=service_tier,
                )
                mode = "check"
            else:
                review = REVIEW_DISABLED_MESSAGE
                mode = "disabled"
            review_finished_at = perf_counter()
            events.put(
                {
                    "event": "sql_review",
                    "review": review,
                    "mode": mode,
                    "duration_seconds": review_finished_at - review_started_at,
                }
            )
            result_started_at = review_finished_at

        def emit_openai_sql(sql: str) -> None:
            nonlocal result_started_at
            sql_ready_at = perf_counter()
            events.put(
                {
                    "event": "sql",
                    "sql": format_sql_for_display(sql),
                    "duration_seconds": sql_ready_at - sql_started_at,
                }
            )
            events.put(
                {
                    "event": "sql_review",
                    "review": OPENAI_GENERATION_SUCCESS_MESSAGE,
                    "mode": "calculation",
                    "duration_seconds": openai_generation_duration,
                }
            )
            result_started_at = perf_counter()

        def run() -> None:
            nonlocal sql_started_at, openai_generation_duration
            try:
                if sql_calculation_enabled:
                    generation_started_at = perf_counter()
                    generated_sql = self.sql_reviewer.generate(
                        cleaned_message,
                        model=openai_model,
                        reasoning_effort=reasoning_effort,
                        service_tier=service_tier,
                    )
                    openai_generation_duration = perf_counter() - generation_started_at
                    sql_started_at = perf_counter()
                    emit_openai_sql(generated_sql)
                    with self._lock:
                        answer = self.service.ask_database(
                            cleaned_message,
                            sql_override=generated_sql,
                        )
                else:
                    with self._lock:
                        answer = self.service.ask_database(
                            cleaned_message,
                            on_sql_ready=emit_local_sql,
                        )
                events.put(
                    {
                        "event": "answer",
                        "answer": answer,
                        "duration_seconds": perf_counter() - result_started_at,
                    }
                )
            except (OpenAIUnavailableError, OpenAISqlGenerationError) as exc:
                failure_duration = perf_counter() - request_started_at
                sql = "-- SQL не сформирован"
                events.put(
                    {
                        "event": "sql",
                        "sql": sql,
                        "duration_seconds": 0.0,
                    }
                )
                events.put(
                    {
                        "event": "sql_review",
                        "review": str(exc),
                        "mode": "calculation",
                        "duration_seconds": failure_duration,
                    }
                )
                events.put(
                    {
                        "event": "answer",
                        "answer": format_sql_response(
                            sql=sql,
                            result_text="Запрос не выполнен.",
                            explanation_text=str(exc),
                        ),
                        "duration_seconds": 0.0,
                    }
                )
            except Exception as exc:
                events.put({"event": "error", "detail": _agent_error_detail(exc)})

        Thread(target=run, daemon=True).start()

        while True:
            event = events.get()
            yield json.dumps(event, ensure_ascii=False) + "\n"
            if event["event"] in {"answer", "error"}:
                break

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
hh_api = HhApiClient()
tools = {
    "forecast_sales": SalesForecastTool(),
    "currency": CurrencyTool(),
}
voice_input = VoiceInputService()
office_calendar = GoogleCalendarService()
app = FastAPI(title="Viled ATLAS LLM Project", version="1.0.0")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.post("/api/voice/transcribe", response_model=VoiceTranscriptionResponse)
async def transcribe_voice(
    file: UploadFile = File(...),
    use_api: bool = Form(False),
) -> VoiceTranscriptionResponse:
    max_audio_bytes = 15 * 1024 * 1024
    if file.content_type and not (
        file.content_type.startswith("audio/")
        or file.content_type == "application/octet-stream"
    ):
        raise HTTPException(status_code=415, detail="Only audio recordings are accepted.")

    audio = await file.read(max_audio_bytes + 1)
    if len(audio) > max_audio_bytes:
        raise HTTPException(status_code=413, detail="Audio recording exceeds the 15 MB limit.")

    try:
        result = await run_in_threadpool(
            voice_input.transcribe,
            audio,
            use_api=use_api,
            filename=file.filename or "voice-input.webm",
            content_type=file.content_type or "application/octet-stream",
        )
    except VoiceInputUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except VoiceInputError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    return VoiceTranscriptionResponse(
        text=result.text,
        language=result.language,
        duration_seconds=result.duration_seconds,
    )


@app.get("/api/status", response_model=StatusResponse)
def status() -> StatusResponse:
    return StatusResponse(
        model=LM_STUDIO_MODEL,
        openai_model="gpt-5.6",
        openai_reasoning_effort="medium",
        openai_service_tier="default",
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


def _calendar_http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, CalendarConfigurationError):
        return HTTPException(status_code=503, detail=str(exc))
    if isinstance(exc, (CalendarApiError, RuntimeError)):
        return HTTPException(status_code=502, detail=str(exc))
    if isinstance(exc, ValueError):
        return HTTPException(status_code=400, detail=str(exc))
    return HTTPException(status_code=500, detail="Ошибка интеграции с Google Calendar.")


@app.get("/api/office-manager/calendar/status", response_model=OfficeCalendarStatusResponse)
def office_calendar_status() -> OfficeCalendarStatusResponse:
    return OfficeCalendarStatusResponse(
        configured=office_calendar.configured,
        calendar_id=office_calendar.calendar_id,
    )


@app.get("/api/office-manager/tasks", response_model=list[OfficeTaskResponse])
def office_tasks() -> list[OfficeTaskResponse]:
    try:
        return [OfficeTaskResponse(**task) for task in office_calendar.list_tasks()]
    except Exception as exc:
        raise _calendar_http_error(exc) from exc


@app.post("/api/office-manager/tasks", response_model=OfficeTaskResponse)
def create_office_task(request: OfficeTaskCreateRequest) -> OfficeTaskResponse:
    try:
        task = office_calendar.create_task(request.title, request.due_at, request.notes)
        return OfficeTaskResponse(**task)
    except Exception as exc:
        raise _calendar_http_error(exc) from exc


@app.patch("/api/office-manager/tasks/{event_id}", response_model=OfficeTaskResponse)
def update_office_task(event_id: str, request: OfficeTaskUpdateRequest) -> OfficeTaskResponse:
    try:
        return OfficeTaskResponse(
            **office_calendar.set_completed(event_id, request.completed),
        )
    except Exception as exc:
        raise _calendar_http_error(exc) from exc


@app.delete("/api/office-manager/tasks/{event_id}", status_code=204)
def delete_office_task(event_id: str) -> None:
    try:
        office_calendar.delete_task(event_id)
    except Exception as exc:
        raise _calendar_http_error(exc) from exc


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


@app.post("/api/chat/stream")
def chat_stream(request: ChatRequest) -> StreamingResponse:
    workspace = _validate_workspace(request.workspace)
    if workspace != "bi_analytics":
        raise HTTPException(status_code=400, detail="Streaming is available for SQL Analytic only.")

    agent = agents[workspace]
    if not isinstance(agent, WebSqlAgent):
        raise HTTPException(status_code=500, detail="SQL agent is not available.")

    try:
        stream = agent.stream(
            request.message,
            openai_model=request.openai_model,
            reasoning_effort=request.reasoning_effort,
            service_tier=request.service_tier,
            sql_calculation_enabled=request.sql_calculation_enabled,
            sql_check_mode_enabled=request.sql_check_mode_enabled,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return StreamingResponse(stream, media_type="application/x-ndjson")


@app.post("/api/sql/export/excel")
def export_sql_excel(request: ExcelExportRequest) -> FileResponse:
    if bool(request.sql) == bool(request.message):
        raise HTTPException(
            status_code=400,
            detail="Передайте либо готовый SQL, либо исходный запрос для экспорта.",
        )

    agent = agents["bi_analytics"]
    if not isinstance(agent, WebSqlAgent):
        raise HTTPException(status_code=500, detail="SQL agent is not available.")

    try:
        with agent._lock:
            sql = request.sql or agent.service.build_export_sql(request.message or "")
            engine = agent.service.database_connector.build_engine()
            path, row_count = export_sql_to_excel(engine, sql)
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
            detail="Ошибка выполнения SQL-запроса при экспорте.",
        ) from exc

    export_filename = _excel_export_filename()
    return FileResponse(
        path,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename=export_filename,
        headers={
            "X-Export-Row-Count": str(row_count),
            "X-Export-Filename": export_filename,
        },
        background=BackgroundTask(path.unlink, missing_ok=True),
    )


def _excel_export_filename(created_at: datetime | None = None) -> str:
    timestamp = (created_at or datetime.now()).strftime("%Y-%m-%d %H-%M-%S")
    return f"viled_atlas_sql_agent {timestamp}.xlsx"


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


@app.get("/api/currency/pricing/latest", response_model=list[CurrencyPricingRow])
def currency_pricing_latest() -> list[CurrencyPricingRow]:
    tool = tools["currency"]
    if not isinstance(tool, CurrencyTool):
        raise HTTPException(status_code=500, detail="Currency tool is not available.")

    try:
        return [CurrencyPricingRow(**row) for row in tool.load_latest_pricing_rows()]
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Currency pricing request failed: {exc}") from exc


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
        message=f"Saved {saved_count} Viled Inform Fact value(s).",
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


@app.get("/api/hr/hh/areas", response_model=list[HhAreaResponse])
def hh_areas() -> list[HhAreaResponse]:
    try:
        return [HhAreaResponse(**area) for area in hh_api.kazakhstan_areas()]
    except HhApiError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@app.post("/api/hr/hh/vacancies", response_model=HhVacancySearchResponse)
def hh_vacancies(request: HhVacancySearchRequest) -> HhVacancySearchResponse:
    try:
        result = hh_api.search_vacancies(
            VacancySearch(
                text=request.text,
                area=request.area,
                experience=request.experience,
                salary=request.salary,
                only_with_salary=request.only_with_salary,
                period=request.period,
                order_by=request.order_by,
                page=request.page,
                per_page=request.per_page,
            )
        )
        return HhVacancySearchResponse(**result)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except HhApiError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@app.post("/api/hr/hh/resumes", response_model=HhResumeSearchResponse)
def hh_resumes(request: HhResumeSearchRequest) -> HhResumeSearchResponse:
    try:
        result = hh_api.search_resumes(
            ResumeSearch(
                text=request.text,
                area=request.area,
                experience=request.experience,
                salary_from=request.salary_from,
                salary_to=request.salary_to,
                only_with_salary=request.only_with_salary,
                education_level=request.education_level,
                job_search_status=request.job_search_status,
                period=request.period,
                order_by=request.order_by,
                page=request.page,
                per_page=request.per_page,
            )
        )
        return HhResumeSearchResponse(**result)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except HhApiError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
