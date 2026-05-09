# Viled LLM Codex Project

## Quick start

1. Create and activate a virtual environment:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

2. Install dependencies:

```powershell
pip install -r requirements.txt
```

3. Configure environment variables:

```powershell
Copy-Item .env.example .env
# then set OPENAI_API_KEY in .env
```

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
