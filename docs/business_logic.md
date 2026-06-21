# Business Logic

This file is the canonical place for business rules, domain vocabulary, and cross-table behavior.

Use `docs/database_schema.md` for physical table structure. Use this file to explain how the business expects those tables to be interpreted.

## Maintenance Checklist

- Define which user words map to which table or domain.
- Define which columns are identifiers, dates, dimensions, and metrics.
- Define default aggregation rules.
- Define currency behavior.
- Define required clarification questions.
- Define join rules and anti-duplication rules before comparing metrics across tables.
- Keep examples read-only.

## Current Domains

| Domain | Main table | Main date column | Main identifier | Default metric |
|---|---|---|---|---|
| Retail prices | `[DWH].[LLM].[price]` | `price_date` | `ware_id` | all retail price currency columns |
| Sales | `[LLM].[sales]` | `sale_date` | `product_id` | `amount` for money, `quantity` for units |
| Product cost | `[DWH].[LLM].[cost]` | `date` | `product_id` | `cost` for operations; `cost_sum` for current balance |

## Retail Price Logic

Use `[DWH].[LLM].[price]` when the user asks about:
- prices;
- retail prices;
- price history;
- price dynamics;
- currency-specific product prices.

Business vocabulary:
| User wording | Meaning | Column/table |
|---|---|---|
| price, цена, цены | Retail price | `[DWH].[LLM].[price]` |
| USD, доллар | USD retail price | `full_retail_price_usd` |
| EUR, евро | EUR retail price | `full_retail_price_eur` |
| KZT, тенге | KZT retail price | `full_retail_price_kzt` |
| price level, диапазон цен | Retail price range/level | `full_price_level_kzt`, `full_price_level_usd`, `full_price_level_eur` |
| brand, бренд | Product brand | `brand` |
| rank, latest rank | Reverse chronological price rank per product | `_RANK` |
| latest, last, последние | Newest records | `ORDER BY price_date DESC` |
| history, динамика | Chronological history | `ORDER BY price_date ASC` |

Default behavior:
- If no currency is specified, show KZT, EUR, and USD retail price columns.
- `_RANK = 1` means the newest price for a `ware_id`; `_RANK = 2` means the previous price, and so on.
- For detailed rows, use `TOP 100` unless the user asks otherwise.
- For previews and samples, use `TOP 10`.
- "Все данные" means all known columns and no `TOP`; requested filters must still be applied.

Clarification rules:
- TODO

Do not:
- Do not use `[DWH].[LLM].[price]` for sales, sold quantity, revenue, or sale documents.
- Do not assume `ware_id` is equal to `[LLM].[sales].[product_id]` unless the mapping is confirmed.

## Sales Logic

Use `[LLM].[sales]` when the user asks about:
- sales;
- sold products;
- revenue;
- quantities sold;
- sale documents;
- payment metrics such as cash, card, loan, or bonus.

Business vocabulary:
| User wording | Meaning | Column/table |
|---|---|---|
| sales, продажи | Sales records or revenue | `[LLM].[sales]` |
| товар, product | Product identifier | `product_id` |
| продано, продавался | Sold quantity unless the user asks by revenue | `quantity` |
| сумма продаж, выручка, оборот | Sales amount in KZT by default | `amount` |
| USD sales | Sales amount in USD | `amount_usd` |
| EUR sales | Sales amount in EUR | `amount_eur` |
| документ, чек | Sale document | `document_number` |

Default behavior:
- For money totals without currency, use `SUM(amount)`.
- For USD totals, use `SUM(amount_usd)`.
- For EUR totals, use `SUM(amount_eur)`.
- For quantity totals, use `SUM(quantity)`.
- For sales-by-product questions, group by `product_id`.
- For sales-by-date questions, group by or filter on `sale_date`.

Clarification rules:
- If the user asks which product sold best without specifying the metric, ask whether to rank by `SUM(quantity)` or by `SUM(amount)`.

Do not:
- Do not use `ware_id` as the product identifier in `[LLM].[sales]`.
- Do not add `COUNT(*) AS row_count` to grouped product rankings unless the user asks for count/number of rows/documents.
- Do not use `customer_name`; `[LLM].[sales]` does not have this column.

## Product Cost Logic

Use `[DWH].[LLM].[cost]` when the user asks about:
- себестоимость товара / product cost / cost price;
- себестоимость единицы;
- операции, влияющие на себестоимость;
- остаток товара и себестоимость остатка after an operation;
- обнуление себестоимости.

Business vocabulary:
| User wording | Meaning | Column/table |
|---|---|---|
| себестоимость, product cost, cost price | Product cost operation or balance | `[DWH].[LLM].[cost]` |
| себестоимость операции, сумма операции | Total operation cost in KZT | `cost` |
| себестоимость единицы | Operation cost per unit in KZT | `cost_per_unit` |
| количество в операции | Operation quantity | `quantity` |
| остаток, остаток товара | Quantity balance after operation | `qnt_sum` |
| себестоимость остатка | Cost of the full balance in KZT | `cost_sum` |
| обнулено, нулевая себестоимость | `cost_sum = 0` indicator | `zeroed` |
| источник, база 1С | Source database | `db` |
| операция, тип операции | Cost operation type | `op_type` |
| документ | Operation document number | `doc_num` |

Default behavior:
- Monetary values are in KZT.
- For operation totals, aggregate `SUM(cost)`; for operation quantities, aggregate `SUM(quantity)`.
- `qnt_sum` and `cost_sum` are running balances. Never sum them across operation rows.
- For the latest/current balance, use the latest row by `date` for each required `product_id` (and also by `db` if the running total is confirmed to be source-specific).
- For latest records, sort by `date DESC`; for history/dynamics, sort by `date ASC`.
- For detailed rows, use `TOP 100`; for previews, use `TOP 10`.
- For "какая себестоимость товара <product_id>", show `date`, `product_id`, `op_type`, `quantity`, `cost`, `cost_per_unit`, `qnt_sum`, and `cost_sum`, ordered by `date DESC`, without `TOP` unless an explicit limit is requested.

Clarification rules:
- If “общая себестоимость” could mean transaction turnover (`SUM(cost)`) or the current inventory balance (`cost_sum`), ask which meaning is intended.

Do not:
- Do not use the retail price columns from `[DWH].[LLM].[price]` as cost.
- Do not calculate revenue or sales from `[DWH].[LLM].[cost]`.
- Do not aggregate `qnt_sum` or `cost_sum` with `SUM` across operation rows.
- Do not join the table to sales or prices until join keys and grain are confirmed.

## Cross-Table Logic

Document confirmed joins here before relying on them in SQL generation.

Relationships:
| Business question | Tables | Join keys | Required pre-aggregation | Notes |
|---|---|---|---|---|
| TODO | TODO | TODO | TODO | TODO |

Potential relationships requiring confirmation:
- `[DWH].[LLM].[cost].[product_id]` to `[LLM].[sales].[product_id]`.
- `[DWH].[LLM].[cost].[product_id]` to `[DWH].[LLM].[price].[ware_id]`.

Anti-duplication rules:
- Aggregate each side to the required grain before joining when both tables can have multiple rows per key.
- Do not compare facts across tables until the grain and join keys are documented.

## New Domain Template

Copy this section when a new business domain is added.

````md
## Domain: TODO

Main table:
- `[schema].[table_name]`

Use this domain when the user asks about:
- TODO

Do not use this domain when:
- TODO

Business vocabulary:
| User wording | Meaning | Column/table |
|---|---|---|
| TODO | TODO | TODO |

Default identifiers:
- TODO

Default date logic:
- Date column: TODO
- Latest sorting: TODO
- History sorting: TODO

Default metrics:
| Question type | Metric expression | Notes |
|---|---|---|
| TODO | TODO | TODO |

Currency rules:
- TODO

Aggregation rules:
- TODO

Clarification rules:
- TODO

Cross-table rules:
- TODO

Example questions:
- TODO

Example SQL:

```sql
SELECT TOP 100
    [column_name]
FROM [schema].[table_name];
```
````
