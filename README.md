# Viled ATLAS LLM Project

## Quick start

Viled ATLAS LLM Project is a local agent team interface with separate agents, chats, memory, and tools.

- `BI Analytics`: SQL Server analytics agent for BI data.
- `Office Manager`: general LLM chat agent without SQL access.
- `HR`: работа с корпоративными PDF, поиск вакансий и поиск сотрудников (резюме) через hh.kz.


1. Create and activate a virtual environment:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

2. Install dependencies:

```powershell
pip install -r requirements.txt
```

3. Configure SQL Server credentials in
   `C:\Users\p.boychenko\secrets\SQL_Password.env`.

```powershell
$env:OPENAI_API_KEY = "your_api_key_here"
```

Для раздела Office Manager → «Список дел» настройте OAuth-приложение Google
Calendar с доступом `https://www.googleapis.com/auth/calendar.events` и задайте:

```powershell
$env:GOOGLE_CALENDAR_CLIENT_ID = "your_client_id"
$env:GOOGLE_CALENDAR_CLIENT_SECRET = "your_client_secret"
$env:GOOGLE_CALENDAR_REFRESH_TOKEN = "your_refresh_token"
$env:GOOGLE_CALENDAR_ID = "primary"
$env:GOOGLE_CALENDAR_TIME_ZONE = "Asia/Qyzylorda"
```

Задачи сохраняются как события Google Calendar. Служебные признаки
`atlasTask` и `atlasDone` записываются в приватные extended properties события;
OAuth-секреты и токены остаются только на FastAPI-сервере.

`OPENAI_API_KEY` enables the OpenAI SQL modes in the BI Analytics web chat.
`SQL CALCULATION` asks OpenAI to create a read-only SQL query instead of the
local agent. `SQL CHECK MODE` asks OpenAI to review SQL created by the local
agent. When both are enabled, OpenAI creates the SQL and the duplicate review is
skipped. OpenAI receives only the user request, generated SQL when reviewing,
and local schema documentation; it has no database tools, never executes SQL,
and never receives query results. Without a key, on connection/API/quota errors,
or when `OPENAI_SQL_REVIEW_ENABLED=0`, the UI shows
`OpenAI API не доступен` with a safe reason.
The model can be changed with `OPENAI_SQL_REVIEW_MODEL` (default: `gpt-5.6`).

Для поиска вакансий создайте `C:\Users\p.boychenko\secrets\HH_API.env`:

```dotenv
HH_CLIENT_ID=ваш_client_id_от_hh
HH_CLIENT_SECRET=ваш_client_secret_от_hh
HH_REDIRECT_URI=http://localhost:8000/callback
HH_APPLICATION_NAME=Название_Вашего_Приложения
```

Сервер автоматически получает токен приложения через `client_credentials` и
хранит его только в памяти процесса. Секрет и токен не передаются в браузер:
запросы к hh.kz выполняет только FastAPI-сервер. `HH_REDIRECT_URI` сохранён для
будущего OAuth-сценария с авторизацией пользователя; для поиска вакансий через
токен приложения callback не требуется.

Вкладка «Поиск сотрудников» использует эндпоинт `/resumes` API hh. Он доступен
только под OAuth-токеном менеджера работодателя с оплаченным доступом к базе
резюме: токен приложения (`client_credentials`) вернёт `403`. Такой токен
задаётся через `HH_ACCESS_TOKEN` в том же `HH_API.env`.

4. Run the CLI:

```powershell
python langchain_sql_agent.py "Покажи последние 10 цен"
```

5. Run the web chat:

```powershell
uvicorn sql_agent.web:app --reload --host 127.0.0.1 --port 8000
```

Open http://127.0.0.1:8000 in a browser.

---

### Running Tests

Small pytest-based tests are provided under `tests/`. You can execute them after
installing the dependencies:

```powershell
pip install -r requirements.txt pytest
pytest
```

### Local LLM (LM Studio)

The local SQL mode uses deterministic intent rules and `SqlBuilder` first. For an
unrecognized intent it can call the OpenAI-compatible LM Studio endpoint at
`http://127.0.0.1:1234/v1`. The configured model is
`llama-3.2-3b-instruct`; both values live in `sql_agent/config.py`.

Start LM Studio, load the model, and verify the endpoint from PowerShell:

```powershell
Invoke-RestMethod -Uri http://127.0.0.1:1234/v1/models
```

With `SQL CALCULATION` and `SQL CHECK MODE` disabled, BI Analytics stays in
the local contour and does not call the external OpenAI API.
