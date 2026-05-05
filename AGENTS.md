# AGENTS.md

Project instructions for Codex and other coding agents working in this repository.

## Communication

- Prefer Russian for explanations, status updates, and user-facing summaries unless the user asks otherwise.
- Keep answers practical and concise. Explain important risks, assumptions, and verification results.
- When discussing SQL results or database behavior, be explicit about table names, columns, filters, sort order, and row limits.

## Project Context

- This is a Python project for working with SQL Server data through scripts and an LLM-assisted SQL agent.
- Important files:
  - `langchain_sql_agent.py`: interactive SQL agent, memory handling, SQL Server connection, LangChain/OpenAI integration.
  - `sql_server_query.py`: direct SQL Server query script.
  - `requirements.txt`: Python dependencies.
  - `.env.example`: safe example environment file.
- Local runtime memory is stored under `.agent_memory/`. Treat it as private local state, not source code.

## Secrets And Local State

- Never commit real secrets, passwords, API keys, database hosts, or private connection strings.
- Keep `.env`, `SQL_Password.env`, and `.agent_memory/` out of Git.
- The current code expects SQL credentials at:
  - `C:\Users\p.boychenko\secrets\SQL_Password.env`
- Do not print secret values in final responses or logs. If checking configuration, only mention whether required keys exist.

## SQL Agent Rules

- Default table for retail price questions: `[BI].[actual_retail_price]`.
- Primary date column: `price_date`.
- Primary product identifier: `ware_id`.
- For detailed row outputs, limit results to 100 rows unless the user asks for more.
- For preview/sample outputs, use 10 rows.
- For "latest", "last", "recent", or "newest" records, sort by `price_date DESC`.
- For price history or dynamics, sort by `price_date ASC` unless the user asks for newest first.
- For retail price output, prefer these columns unless the user asks otherwise:
  - `price_date`
  - `ware_id`
  - `full_retail_price_kzt`
  - `full_retail_price_eur`
  - `full_retail_price_usd`
- If the user asks for prices without specifying a currency, show all three price columns:
  - `full_retail_price_kzt`
  - `full_retail_price_eur`
  - `full_retail_price_usd`
- Currency mapping:
  - USD: `usd`, `dol`, `dollar`, `dollars`, `дол`, `доллар`, `доллары` -> `full_retail_price_usd`
  - KZT: `kzt`, `tenge`, `тенге` -> `full_retail_price_kzt`
  - EUR: `eur`, `euro`, `евро` -> `full_retail_price_eur`
- Use only columns that exist in the inspected schema. Do not invent business fields.

## Coding Style

- Follow the existing Python style in the repository.
- Keep changes small and focused on the user's request.
- Prefer clear functions and explicit names over clever abstractions.
- Use `pathlib.Path` for filesystem paths when editing Python code.
- Use parameterized SQL or SQLAlchemy `text()` where appropriate. Avoid building SQL from untrusted user input without validation.
- Preserve Windows/PowerShell compatibility in examples and commands.

## Testing And Verification

- After code changes, run the most relevant lightweight check available.
- Good default checks:
  - `python -m compileall .`
  - `python langchain_sql_agent.py --help` if CLI behavior changed.
  - `python sql_server_query.py` only when database access is intentionally being tested.
- Do not run database queries casually if the task does not require live DB access.
- If a check cannot be run because credentials, drivers, network, or local services are missing, state that clearly.

## Git Hygiene

- Do not revert user changes unless the user explicitly asks.
- Before committing, check `git status --short`.
- Do not include `.env`, `.agent_memory/`, virtual environments, caches, or generated local data in commits.
- Use concise commit messages in English unless the user requests Russian.

