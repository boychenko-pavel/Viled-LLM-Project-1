# Viled ATLAS LLM Project

## Quick start

Viled ATLAS LLM Project is a local agent team interface with separate agents, chats, memory, and tools.

- `BI Analytics`: SQL Server analytics agent for BI data.
- `Office Manager`: general LLM chat agent without SQL access.


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

## New Analytics & LLM Features

The project now includes a simple analytics system backed by a local database and a wrapper
for a local Olama LLM. The `app.py` script exposes additional commands:

* `python main.py status` – original env check (also default).
* `python main.py analyze --product Foo` – show summary statistics and a naive linear
  forecast for the given product. Uses SQLite by default; set `DATABASE_URL` to
  point at another SQL database. The schema is defined in `src/viled_llm/database.py`.
* `python main.py teach "prompt text" "example response"` – store an
  example that will later be concatenated when querying the LLM.

### Database Setup

### Running Tests

Small pytest-based tests are provided under `tests/`. You can execute them after
installing the dependencies:

```powershell
pip install -r requirements.txt pytest
pytest
```

### Database Setup

By default the database file is `./data.db`. Run the following from a Python REPL or in
scripts to create tables and add rows:

```python
from src.viled_llm import database

database.init_db()
s = database.SessionLocal()
database.add_sale(s, "Widget", 10, 2.99)
```

### Local LLM (Olama)

The code assumes you have the `olama` binary installed and in your PATH.  Set
`OLAMA_MODEL` if you want to override the default model name.  Example usage from
Python:

```python
from src.viled_llm.llm import OlamaClient

client = OlamaClient()
client.add_example("Hello", "Hi there!")
print(client.generate_with_examples("Hello"))
```

