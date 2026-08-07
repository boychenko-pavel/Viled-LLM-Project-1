# CLAUDE.md

Single source of project rules: @AGENTS.md — read it before any task.
This file only adds Claude Code specific notes; do not duplicate rules here.

## Reference Documents

- `docs/database_schema.md`: table dictionary, grain, columns, joins.
- `docs/business_logic.md`: business rules and cross-table logic.
- `docs/sql_agent_architecture.md`: component overview.
- `start-stop.md`: start/stop the web server and git workflow.

## Environment

- Windows 11 with PowerShell. Use PowerShell syntax in commands and examples; do not assume bash.
- Virtual environment: `.\.venv\Scripts\Activate.ps1`, interpreter `.\.venv\Scripts\python.exe`.
- `BI Analytics` requires VPN, because SQL Server is reachable only through VPN.
- `Office Manager` and the local LLM fallback require LM Studio at `http://127.0.0.1:1234/v1`.
- Web server: `python -m uvicorn sql_agent.web:app --host 127.0.0.1 --port 8000`.

## Verification

- Default check after code changes: `pytest`.
- Syntax-only check: `python -m compileall .`.
- Do not run database-backed checks unless the task requires live SQL Server access.

## Local State And Secrets

- `C:\Users\p.boychenko\secrets\` holds real credentials. Reading it is denied in
  `.claude/settings.json`. Never read, copy, or print its contents.
- `.agent_memory/` and `.models/` are local runtime state, not source code.
- `sqlite/data.db` is a tracked binary snapshot; do not rewrite it as a side effect of another change.
- `.env` files are denied for reading. Only `.env.example` documents required keys.

## Large Modules

`sql_agent/intent_parser.py` (~3500 lines) and `sql_agent/sql_builder.py` (~1700 lines) are the
largest files. Use targeted `Grep` searches instead of full reads.
