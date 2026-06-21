# Database Schema

This file is the canonical place for SQL Server table dictionaries, physical schema notes, and relationship details.

Use `AGENTS.md` only for short rules that the assistant must always follow. Put fuller table descriptions here.

## Maintenance Checklist

- Confirm the table exists in SQL Server before documenting it.
- List only columns that exist in the inspected schema.
- Describe the grain: what one row represents.
- Mark primary date columns, identifiers, metrics, currency columns, and nullable fields.
- Document relationships with exact table names and columns.
- Note any join that is conceptual or business-defined rather than enforced by a key.
- Add sample read-only `SELECT` queries when they clarify expected usage.

## Current Supported Tables

These tables are currently referenced by deterministic intent parsing and SQL generation:

- `[DWH].[LLM].[price]`
- `[LLM].[sales]`
- `[DWH].[LLM].[cost]`

## Table: [DWH].[LLM].[price]

Purpose:
Stores product retail price setup and change records including VAT.

Grain:
One row per product retail price value/change for a `ware_id` and `price_date`.

Primary date column:
- `price_date`

Primary identifiers:
- `ware_id`

Preferred columns:
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

Columns:
| Column | Data type | Meaning | Nullable | Notes |
|---|---|---|---|---|
| `price_date` | TODO | Date when the retail price was set or changed | TODO | Primary date column |
| `ware_id` | TODO | Unique product identifier, Sprut code | TODO | Primary identifier for this table |
| `full_retail_price_kzt` | TODO | Retail price including VAT in KZT | TODO | Currency metric |
| `full_retail_price_eur` | TODO | Retail price including VAT in EUR | TODO | Currency metric |
| `full_retail_price_usd` | TODO | Retail price including VAT in USD | TODO | Currency metric |
| `full_price_level_kzt` | TODO | Price range/level for this price value in KZT | TODO | Price level dimension |
| `full_price_level_usd` | TODO | Price range/level for this price value in USD | TODO | Price level dimension |
| `full_price_level_eur` | TODO | Price range/level for this price value in EUR | TODO | Price level dimension |
| `_RANK` | TODO | Reverse chronological rank of the price per `ware_id` | TODO | Newest `price_date` has rank 1, previous has rank 2, etc. |
| `brand` | TODO | Product brand | TODO | Product dimension |

Relationships:
| From table | From column | To table | To column | Cardinality | Notes |
|---|---|---|---|---|---|
| `[DWH].[LLM].[price]` | `ware_id` | TODO | TODO | TODO | Do not assume it equals `[LLM].[sales].[product_id]` unless confirmed |

Sample queries:

```sql
SELECT TOP 100
    [price_date],
    [ware_id],
    [full_retail_price_kzt],
    [full_retail_price_eur],
    [full_retail_price_usd],
    [full_price_level_kzt],
    [full_price_level_usd],
    [full_price_level_eur],
    [_RANK],
    [brand]
FROM [DWH].[LLM].[price]
ORDER BY [price_date] DESC;
```

Open questions:
- TODO

## Table: [DWH].[LLM].[cost]

Purpose:
Stores product cost operations and the resulting inventory quantity and cost balances.

Grain:
One row per product cost operation/document line for a `product_id` and `date` from a 1C source database.

Primary date column:
- `date`

Primary identifiers:
- `product_id` (Sprut code)
- `doc_num` (operation document number)

Preferred columns:
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

Columns:
| Column | Data type | Meaning | Nullable | Notes |
|---|---|---|---|---|
| `db` | TODO | Source 1C database | TODO | Source dimension |
| `date` | datetime | Operation date in `YYYY-MM-DD 00:00:00.000` format | TODO | Primary date column |
| `op_type` | TODO | Operation type | TODO | See allowed values below |
| `doc_num` | TODO | Document number | TODO | Operation document reference |
| `product_id` | TODO | Unique product identifier, Sprut code | TODO | Primary product identifier |
| `quantity` | TODO | Quantity in the operation, units | TODO | Additive operation metric |
| `cost` | TODO | Total cost of the operation in KZT | TODO | Additive operation metric |
| `cost_per_unit` | TODO | Cost per unit in KZT for the operation | TODO | Calculated as `cost / quantity`; guard against zero quantity when recalculating |
| `qnt_sum` | TODO | Product quantity balance after the operation | TODO | Running total of `quantity` by `date`; not additive across rows |
| `cost_sum` | TODO | Cost of the full product balance after the operation in KZT | TODO | Running total of `cost` by `date`; not additive across rows |
| `zeroed` | TODO | Indicator that `cost_sum = 0` | TODO | Confirm physical data type and exact true/false values |

Known `op_type` values:
| Code | Operation names |
|---|---|
| `0` | Ввод остатков |
| `1` | Корректировка; Оприходование; Поступление |
| `2` | ГТД; Доп. расходы |
| `3` | Возврат поставщику; Списание |
| `4` | Реализация |
| `5` | Возврат от покупателя |

Relationships:
| From table | From column | To table | To column | Cardinality | Notes |
|---|---|---|---|---|---|
| `[DWH].[LLM].[cost]` | `product_id` | `[LLM].[sales]` | `product_id` | TODO | Same business identifier name, but join validity and grain must be confirmed before use |
| `[DWH].[LLM].[cost]` | `product_id` | `[DWH].[LLM].[price]` | `ware_id` | TODO | Possible Sprut-code relationship; do not join until confirmed |

Default sorting:
- Latest/current operation or balance: `date DESC`.
- Cost history or dynamics: `date ASC`.

Sample query:

```sql
SELECT TOP 100
    [db],
    [date],
    [op_type],
    [doc_num],
    [product_id],
    [quantity],
    [cost],
    [cost_per_unit],
    [qnt_sum],
    [cost_sum],
    [zeroed]
FROM [DWH].[LLM].[cost]
ORDER BY [date] DESC;
```

Open questions:
- Confirm physical data types and nullability.
- Confirm the row grain when one document contains multiple lines for the same product.
- Confirm whether running totals are partitioned by both `db` and `product_id`.
- Confirm whether `product_id` can be safely joined to `[LLM].[sales].[product_id]` and `[DWH].[LLM].[price].[ware_id]`.

## Table: [LLM].[sales]

Purpose:
TODO: describe the business purpose of the table.

Grain:
TODO: one row per sale line / document line / transaction line.

Primary date column:
- `sale_date`

Primary identifiers:
- `document_number`
- `product_id`

Preferred columns:
- `sale_date`
- `document_number`
- `product_id`
- `quantity`
- `amount`
- `amount_usd`
- `amount_eur`

Columns:
| Column | Data type | Meaning | Nullable | Notes |
|---|---|---|---|---|
| `sale_date` | TODO | Sale date | TODO | Primary date column |
| `document_number` | TODO | 1C document number | TODO | Sale document reference |
| `product_id` | TODO | Unique product code | TODO | Primary product identifier |
| `quantity` | TODO | Quantity of sold product | TODO | Quantity metric |
| `amount` | TODO | Sale amount in KZT | TODO | Default sales amount metric |
| `amount_usd` | TODO | Sale amount in USD | TODO | Currency metric |
| `amount_eur` | TODO | Sale amount in EUR | TODO | Currency metric |

Relationships:
| From table | From column | To table | To column | Cardinality | Notes |
|---|---|---|---|---|---|
| `[LLM].[sales]` | `product_id` | TODO | TODO | TODO | Use for sales-by-product logic |

Sample queries:

```sql
SELECT TOP 100
    [sale_date],
    [document_number],
    [product_id],
    [quantity],
    [amount],
    [amount_usd],
    [amount_eur]
FROM [LLM].[sales]
ORDER BY [sale_date] DESC;
```

Open questions:
- TODO

## New Table Template

Copy this section for each new table.

````md
## Table: [schema].[table_name]

Purpose:
TODO

Grain:
One row per TODO.

Primary date column:
- TODO

Primary identifiers:
- TODO

Metrics:
- TODO

Currency columns:
- TODO

Columns:
| Column | Data type | Meaning | Nullable | Notes |
|---|---|---|---|---|
| `column_name` | TODO | TODO | TODO | TODO |

Relationships:
| From table | From column | To table | To column | Cardinality | Notes |
|---|---|---|---|---|---|
| `[schema].[table_name]` | TODO | TODO | TODO | TODO | TODO |

Default filters:
- TODO

Default sorting:
- TODO

Sample queries:

```sql
SELECT TOP 100
    [column_name]
FROM [schema].[table_name];
```

Open questions:
- TODO
````
