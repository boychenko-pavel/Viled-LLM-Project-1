# AGENTS.md

Project instructions for Codex and other coding agents working in Viled ATLAS LLM Project.

## Communication

- Prefer Russian for explanations, status updates, and user-facing summaries unless the user asks otherwise.
- Keep answers practical and concise. Explain important risks, assumptions, and verification results.
- Use the shortest answer that fully solves the request. Avoid restating the task, long preambles, generic explanations, and repeated summaries.
- For code changes, final responses should normally include only: what changed, how it was verified, and any relevant limitation or next action.
- When discussing SQL results or database behavior, be explicit about table names, columns, filters, sort order, and row limits.

## Token And Context Economy

- Read only the files needed for the current task; prefer targeted `rg` searches and focused file reads over broad exploration.
- Do not paste long command outputs, diffs, logs, or code blocks into replies unless the user asks for them. Summarize the important lines instead.
- Keep intermediate status updates brief and meaningful; skip them for very small tasks that can be completed immediately.
- Preserve code quality while minimizing churn: make small scoped edits, avoid unrelated refactors, and follow existing project patterns.
- Add tests or checks proportional to the risk of the change; do not run expensive or database-backed checks unless they are necessary or requested.

## Project Context

- Project name: `Viled ATLAS LLM Project`.
- This is a Python project for working with SQL Server data through scripts and an intent-driven SQL assistant.
- The web UI presents a team of agents, not generic workspaces:
  - `BI Analytics`: SQL/BI agent with SQL Server access and BI memory.
  - `Office Manager`: general LLM chat agent with separate memory and no SQL tools.
- Important files:
  - `langchain_sql_agent.py`: CLI entrypoint and compatibility exports.
  - `sql_agent/service.py`: main orchestration layer.
  - `sql_agent/intent_parser.py`: rule-first and LLM-assisted intent parsing.
  - `sql_agent/sql_builder.py`: deterministic SQL generation and response formatting.
  - `sql_agent/schema.py`: SQL Server schema snapshot inspection.
  - `sql_server_query.py`: direct SQL Server query script.
- Local runtime memory is stored under `.agent_memory/`. Treat it as private local state, not source code.

## Voice Input

- All local speech-to-text implementation belongs in `sql_agent/voice_input.py`.
- Read or change that module only for voice recording, transcription, model, or microphone tasks.
- Other project code must use `VoiceInputService`; do not import `faster_whisper` outside the voice module.
- The web endpoint is `/api/voice/transcribe`; browser recording is implemented in `web/static/app.js`.
- Models are local runtime data under `.models/faster-whisper/` and must not be committed.

## Secrets And Local State

- Never commit real secrets, passwords, API keys, database hosts, or private connection strings.
- Keep `.env`, `SQL_Password.env`, and `.agent_memory/` out of Git.
- The current code expects SQL credentials at `C:\Users\p.boychenko\secrets\SQL_Password.env`.
- Do not print secret values in final responses or logs. If checking configuration, only mention whether required keys exist.

## SQL Schema Documentation

- Canonical SQL schema notes live in `docs/database_schema.md`.
- Canonical business rules and cross-table logic live in `docs/business_logic.md`.
- Keep short, agent-critical rules in this `AGENTS.md` file.
- Put full table dictionaries, relationships, grain, examples, and pending questions in the `docs/` files.
- When new SQL Server tables are added:
  - document each table's grain: what one row represents;
  - document primary date columns, identifiers, metrics, and currencies;
  - document allowed joins and join keys;
  - document business synonyms in Russian and English;
  - state when the table should not be used;
  - update `sql_agent/intent_parser.py` and `sql_agent/sql_builder.py` only if the assistant must generate deterministic SQL for the new domain.
- Use only columns that exist in the inspected SQL Server schema. The project can inspect visible tables through `sql_agent/schema.py`.

## SQL Domains

- Retail price table: `[DWH].[LLM].[price]`
- Sales table: `[LLM].[sales]`
- Product cost table: `[DWH].[LLM].[cost]`
- Stock movement table: `[DWH].[LLM].[stock]`
- Purchases table: `[DWH].[LLM].[v_Purchases]`
- Product dimension table: `[DWH].[LLM].[dimension_product]`
- `[LLM].[sales]` replaces old `[BI].[sales_table]`.

### Product Dimension Rules

- Table: `[DWH].[LLM].[dimension_product]`
- Table meaning: product master data / dictionary for the unique `product_id` used by other product-related tables.
- Primary identifier: `product_id`.
- No primary date column.
- Preferred output columns are all known product attributes documented in `docs/database_schema.md`, including `product_id`, `article`, `name`, `brand`, `bu`, `category`, `group`, `subgroup`, `product`, `season_short`, `season`, `gender`, `common_size`, `barcode`, `url`, and `image_url`.
- Use this table for questions about product attributes, product dictionary, номенклатура, карточка товара, article/артикул, brand/бренд, BU, category, season, size, color, barcode, buyer, composition, URL, image URL, AML, carryover, or consignment.
- `article` can repeat across products. If products inside one `brand` have the same `article`, they are the same product.
- For `bu = Fashion`, `article` is assembled from `style`, `fabric`, `color_code`, `common_size`, and `season_short` with suffix `1` for `SS` and `2` for `FW`; for other `bu` values, article is provided by the manufacturer.
- `season_short` beginning with `SS` means Spring Summer, from March 1 through the end of August. `season_short` beginning with `FW` means Fall Winter, from September 1 through the end of February.
- Do not use product dimension columns as additive metrics, except `COUNT(*)` for product counts.
- Treat `[DWH].[LLM].[dimension_product]` as the dimension table and the price, sales, cost, stock, and purchases tables as value/fact tables.
- When a value-table request contains a product-dimension attribute such as article, BU/business direction, collection, brand, category, season, size, color, barcode, buyer, or another documented product attribute, join `dimension_product` and apply the attribute there as a filter.
- Join value tables to `dimension_product` by `product_id`; for `[DWH].[LLM].[price]`, use `price.ware_id = dimension_product.product_id`.

### Retail Price Rules

- Primary date column: `price_date`
- Primary product/warehouse identifier used by this table: `ware_id`
- Preferred output columns:
  - `price_date`
  - `ware_id`
  - `full_retail_price_kzt`
  - `full_retail_price_eur`
  - `full_retail_price_usd`
  - `full_price_level_kzt`
  - `full_price_level_usd`
  - `full_price_level_eur`
  - `_RANK`
  - `brand`
- Table meaning: retail price installation/change records for products, including VAT.
- Column meanings:
  - `price_date`: date when the retail price was set or changed.
  - `ware_id`: unique product identifier, Sprut code.
  - `full_retail_price_kzt`: retail price including VAT in KZT.
  - `full_retail_price_eur`: retail price including VAT in EUR.
  - `full_retail_price_usd`: retail price including VAT in USD.
  - `full_price_level_kzt`: price range/level for the KZT price value.
  - `full_price_level_usd`: price range/level for the USD price value.
  - `full_price_level_eur`: price range/level for the EUR price value.
  - `_RANK`: reverse chronological rank of the price per `ware_id`; newest date is 1, previous is 2, etc.
  - `brand`: product brand.
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
- In sales questions, "product", "товар", "товара", "товару", and "товаров" mean `product_id`; do not map product to `ware_id`.
- `ware_id` is not the product identifier for `[LLM].[sales]`.
- `[LLM].[sales]` does not have `customer_name`.
- Preferred output columns:
  - `sale_date`
  - `document_number`
  - `product_id`
  - `quantity`
  - `amount`
  - `amount_usd`
  - `amount_eur`
- Column meanings:
  - `sale_date`: sale date.
  - `document_number`: 1C document number where the sale is recorded.
  - `product_id`: unique product code.
  - `quantity`: quantity of sold product.
  - `amount`: sale amount in KZT.
  - `amount_usd`: sale amount in USD.
  - `amount_eur`: sale amount in EUR.
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
- Questions containing "продавался", "продано", "проданный", "sales", or "продаж" should generally use `[LLM].[sales]`, not `[DWH].[LLM].[price]`.
- If the user asks which product sold best / "какой товар продавался лучше всего" without saying whether "best" means quantity or sales amount, ask a clarification question instead of generating SQL.
- If the user clarifies "по количеству", rank products by `SUM(quantity)`.
- If the user clarifies "по сумме продаж", "по выручке", "по обороту", or similar, rank products by `SUM(amount)` unless a currency is specified.
- For grouped aggregate rankings by product, return the grouping key and aggregate metric; do not add `COUNT(*) AS row_count` unless the user asked for count/number of rows/documents.
- Sales currency mapping:
  - USD totals or amounts -> `amount_usd`
  - EUR totals or amounts -> `amount_eur`
  - KZT or unspecified totals or amounts -> `amount`

### Product Cost Rules

- Primary date column: `date`
- Primary product identifier: `product_id` (Sprut code)
- Preferred output columns:
  - `db`
  - `date`
  - `op_type`
  - `doc_num`
  - `product_id`
  - `quantity`
  - `cost`
  - `cost_per_unit`
  - `qnt_sum`
  - `cost_sum`
  - `zeroed`
- Table meaning: product cost operations and the resulting running quantity and cost balances.
- `cost` is the total operation cost in KZT; `cost_per_unit = cost / quantity`.
- `qnt_sum` and `cost_sum` are running balances after the operation, ordered by `date`.
- `zeroed` marks rows where `cost_sum = 0`.
- Use `[DWH].[LLM].[cost]` for questions about себестоимость, cost price, inventory cost, cost per unit, or cost balances.
- For latest/current balances, sort by `date DESC`; for history/dynamics, sort by `date ASC`.
- For a generic "какая себестоимость товара <product_id>" request, return `date`, `product_id`, `op_type`, `quantity`, `cost`, `cost_per_unit`, `qnt_sum`, and `cost_sum`, ordered by `date DESC`, without `TOP` unless the user explicitly requests a limit.
- Do not sum `qnt_sum` or `cost_sum` across operation rows: they are running balances, not additive transaction metrics.
- Do not join `product_id` to other tables until the relationship and grain are confirmed.

### Stock Movement Rules

- Primary date column: `date`
- Primary product identifier: `product_id`
- Primary warehouse identifier: `warehouse_id`
- Preferred output columns:
  - `source_database`
  - `date`
  - `recorder_type`
  - `recorder_type_guid`
  - `recorder_guid`
  - `warehouse_id`
  - `product_id`
  - `quantity`
  - `amount`
  - `document_id`
  - `movement_index`
- Table meaning: product stock movement operations, including transfers between warehouses.
- Column meanings:
  - `source_database`: source data system/database.
  - `date`: operation/document date, e.g. `2026-05-21 22:56:37.000`.
  - `recorder_type`: operation name, e.g. `ввод_остатков`, `Перемещение товаров`, `Поступление товаров и услуг`, `Реализация товаров и услуг`, `Списание товаров`.
  - `recorder_type_guid`: operation code for the `source_database` + `recorder_type` pair.
  - `recorder_guid`: 1C document identifier; equal values mean one common 1C document.
  - `warehouse_id`: warehouse identifier.
  - `product_id`: unique product code.
  - `quantity`: signed operation quantity; positive is receipt to warehouse, negative is issue from warehouse.
  - `amount`: not used for stock logic.
  - `document_id`: 1C document number, e.g. `УТVF0000549`.
  - `movement_index`: product operation sequence number ordered by `date` from older to newer.
- Use `[DWH].[LLM].[stock]` for questions about stock balances, stock movements, warehouse transfers, `Перемещение товаров`, transfer document numbers / 1C document numbers, or direct references to the table.
- For stock at the beginning of a period, use `SUM(quantity)` for operations before the calculation date: `date < period_start`.
- For stock at the end of a period, use `SUM(quantity)` for operations through the calculation date: `date <= period_end`.
- For latest/current movement rows, sort by `date DESC`; for movement history/dynamics, sort by `date ASC`.
- Do not use `amount` as a financial metric.
- Do not join stock to sales, prices, or cost until relationship and grain are confirmed.

### Purchases Rules

- Primary date column: `purchase_date`
- Primary product identifier: `product_id`
- Table meaning: purchase cost operation data for products.
- Preferred output columns:
  - `source_database`
  - `purchase_date`
  - `recorder_type`
  - `recorder_number`
  - `product_id`
  - `quantity`
  - `division_id`
  - `amount_kzt`
  - `NDS_kzt`
  - `amount_usd`
  - `NDS_usd`
  - `amount_eur`
  - `NDS_eur`
  - `amount_chf`
  - `NDS_chf`
- Use `[DWH].[LLM].[v_Purchases]` for questions about закупочная стоимость, purchase cost, purchases/procurement, supplier returns, import declarations, additional purchase expenses, purchase receipts, or purchase VAT.
- `amount_kzt`, `amount_usd`, `amount_eur`, and `amount_chf` are full operation costs for the whole `quantity`.
- Unit purchase cost is `amount_* / quantity` when `quantity <> 0`; use `NULLIF(quantity, 0)` when calculating this in SQL.
- If the user asks for purchase amounts without specifying a currency, use `amount_kzt`.
- Purchase currency mapping:
  - USD amounts -> `amount_usd`
  - EUR amounts -> `amount_eur`
  - CHF amounts -> `amount_chf`
  - KZT or unspecified amounts -> `amount_kzt`
- Purchase VAT mapping:
  - USD VAT -> `NDS_usd`
  - EUR VAT -> `NDS_eur`
  - CHF VAT -> `NDS_chf`
  - KZT or unspecified VAT -> `NDS_kzt`
- Allowed `recorder_type` values: `Возврат товаров поставщику`, `ГТД по импорту`, `Поступление доп. расходов`, `Поступление товаров и услуг`.
- For latest/current purchase rows, sort by `purchase_date DESC`; for history/dynamics, sort by `purchase_date ASC`.
- Do not join purchases to sales, stock, prices, or cost until relationship and grain are confirmed.

### Gross Margin Rules

- Recognize `GM`, `Gross Margin`, `ГМ`, `Маржинальность`, and `Маржа` as the same deterministic calculation.
- Calculate GM at Sprut-code level (`product_id`) even when the request uses `article` or `brand`; show every matching product code within the 100-row web safety limit.
- For GM only, join `price.ware_id`, `stock.product_id`, `cost.product_id`, and `dimension_product.product_id` as the same Sprut product code.
- Do not filter products by stock availability by default.
- If the user explicitly says `в наличии` or `на остатках`, include only products
  with current `SUM(stock.quantity) > 0`.
- Use the latest effective `full_retail_price_kzt` per product and remove 16% VAT by dividing by `1.16`.
- Use current average unit cost from the latest cost balance row as `cost_sum / NULLIF(qnt_sum, 0)`.
- `gross_margin_kzt = price_without_vat - unit_cost_kzt`.
- `gross_margin_percent = gross_margin_kzt / NULLIF(price_without_vat, 0) * 100`.
- GM reports must return columns in this order: `остаток`, `product_id`, `article`, `brand`, `name`, `price_date`, `cost_date`, `retail_price_kzt_incl_vat`, `retail_price_kzt_excl_vat`, `cost_kzt_per_unit`, `gross_profit_kzt_per_unit`, `gross_margin_percent`.

## Query Behavior

- For detailed row outputs, limit results to 100 rows unless the user asks for more.
- For preview or sample outputs, use 10 rows.
- Never return an unbounded detailed result set through the web chat UI. The backend currently uses `fetchall()` and the frontend renders every returned row as HTML table cells; a large response can exhaust Chromium renderer memory and crash the tab with `STATUS_BREAKPOINT`.
- In web-chat requests, interpret "все данные" as all known columns, not unlimited rows, and keep the 100-row limit unless the user gives a smaller explicit limit.
- If the user explicitly asks for all rows or no limit, do not execute or render the unbounded result in web chat. Explain the UI safety limit and require a paginated/export workflow. Implement pagination, streaming, or file export before allowing such a request; the export path may omit `TOP` but must not build the complete result as one Python list, response string, or browser DOM table.
- If the user asks for all columns / "все колонки" / "все столбцы" while also asking for rows, select the known preferred columns for the target table; do not treat this as a schema-only question.
- If the user explicitly writes a SQL `SELECT`, execute the user's read-only `SELECT` as written instead of converting it into an intent. Block non-SELECT statements and multiple statements.
- If the assistant asks a clarification question and the next user message is a short metric clarification, combine it with the previous user question before parsing SQL intent.
- Understand Russian month names in date filters. Examples:
  - `март 2025`, `в марте 2025`, `за март 2025` -> `YYYY-03-01` through the last day of March.
  - `январь-февраль 2025`, `с января по февраль 2025` -> range from the first day of January through the last day of February.
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
