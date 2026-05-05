# AGENTS.md

Project instructions for Codex and other coding agents working in this repository.

## Communication

- Prefer Russian for explanations, status updates, and user-facing summaries unless the user asks otherwise.
- Keep answers practical and concise. Explain important risks, assumptions, and verification results.
- When discussing SQL results or database behavior, be explicit about table names, columns, filters, sort order, and row limits.

## Project Context

- This is a Python project for working with SQL Server data through scripts and an intent-driven SQL assistant.
- Important files:
  - `langchain_sql_agent.py`: CLI entrypoint and compatibility exports.
  - `sql_agent/service.py`: main orchestration layer.
  - `sql_agent/intent_parser.py`: rule-first and LLM-assisted intent parsing.
  - `sql_agent/sql_builder.py`: deterministic SQL generation and response formatting.
  - `sql_server_query.py`: direct SQL Server query script.
- Local runtime memory is stored under `.agent_memory/`. Treat it as private local state, not source code.

## Secrets And Local State

- Never commit real secrets, passwords, API keys, database hosts, or private connection strings.
- Keep `.env`, `SQL_Password.env`, and `.agent_memory/` out of Git.
- The current code expects SQL credentials at `C:\Users\p.boychenko\secrets\SQL_Password.env`.
- Do not print secret values in final responses or logs. If checking configuration, only mention whether required keys exist.

## SQL Domains

- Retail price table: `[BI].[actual_retail_price]`
- Sales table: `[BI].[sales_table]`

### Retail Price Rules

- Primary date column: `price_date`
- Primary product identifier: `ware_id`
- Preferred output columns:
  - `price_date`
  - `ware_id`
  - `full_retail_price_kzt`
  - `full_retail_price_eur`
  - `full_retail_price_usd`
- If the user asks for prices without specifying a currency, show all three price columns.
- Currency mapping:
  - USD aliases -> `full_retail_price_usd`
  - EUR aliases -> `full_retail_price_eur`
  - KZT aliases -> `full_retail_price_kzt`
- For "latest", "last", "recent", or "newest" records, sort by `price_date DESC`.
- For price history or dynamics, sort by `price_date ASC` unless the user asks for newest first.

### Sales Rules

- Primary date column: `sale_date`
- Primary product identifier: `product_id`
- Preferred output columns:
  - `sale_date`
  - `document_number`
  - `product_id`
  - `quantity`
  - `amount`
  - `amount_usd`
  - `amount_eur`
- Common sales metrics:
  - `quantity`
  - `price`
  - `amount`
  - `amount_usd`
  - `amount_eur`
  - `discount`
  - `cash`
  - `card`
  - `loan`
  - `bonus`
- For sales-by-date questions, use `sale_date`.
- For sales-by-product questions, group by `product_id`.
- Sales currency mapping:
  - USD totals or amounts -> `amount_usd`
  - EUR totals or amounts -> `amount_eur`
  - KZT or unspecified totals or amounts -> `amount`

## Query Behavior

- For detailed row outputs, limit results to 100 rows unless the user asks for more.
- For preview or sample outputs, use 10 rows.
- If the user explicitly asks for all rows or says not to use a limit, do not add `TOP`.
- Use only columns that exist in the inspected schema. Do not invent business fields.
- Prefer deterministic SQL generation from structured intent over free-form SQL generation by the model.

## Coding Style

- Follow the existing Python style in the repository.
- Keep changes small and focused on the user's request.
- Prefer clear functions and explicit names over clever abstractions.
- Use `pathlib.Path` for filesystem paths when editing Python code.
- Use parameterized SQL or SQLAlchemy `text()` where appropriate. Avoid building SQL from untrusted user input without validation.
- Preserve Windows and PowerShell compatibility in examples and commands.

## Testing And Verification

- After code changes, run the most relevant lightweight check available.
- Good default checks:
  - `python -m compileall .`
  - `python langchain_sql_agent.py --help` if CLI behavior changed.
  - `python langchain_sql_agent.py "sample question"` for focused smoke tests.
- Do not run database queries casually if the task does not require live DB access.
- If a check cannot be run because credentials, drivers, network, or local services are missing, state that clearly.

## Git Hygiene

- Do not revert user changes unless the user explicitly asks.
- Before committing, check `git status --short`.
- Do not include `.env`, `.agent_memory/`, virtual environments, caches, or generated local data in commits.
- Use concise commit messages in English unless the user requests Russian.
