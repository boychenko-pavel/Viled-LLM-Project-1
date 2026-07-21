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
- `[DWH].[LLM].[stock]`
- `[DWH].[LLM].[v_Purchases]`
- `[DWH].[LLM].[dimension_product]`
- `[DWH].[LLM].[division]`

## Table: [DWH].[LLM].[dimension_product]

Purpose:
Stores product master data. This table is the dictionary for the unique `product_id` used by the other product-related tables.

Grain:
One row per unique product identifier `product_id`.

Primary date column:
- None.

Primary identifiers:
- `product_id`

Preferred columns:
- `product_id`
- `article`
- `style`
- `fabric`
- `color_code`
- `name`
- `breadcrumbs`
- `bu`
- `category`
- `group`
- `subgroup`
- `product`
- `department`
- `subdepartment`
- `department_vs`
- `subdepartment_vs`
- `brand`
- `season_year`
- `season_short`
- `season`
- `gender`
- `sizechart_type`
- `sizechart`
- `common_size`
- `italian_size`
- `color_eng`
- `color_rus`
- `country`
- `buyer`
- `buyer_assistant`
- `composition`
- `fur`
- `heel`
- `brand_category`
- `individual_number`
- `consigment`
- `carryover`
- `stock_year`
- `world_retail_price`
- `collection_jw`
- `store_jw`
- `volume`
- `tone`
- `line`
- `department_en`
- `url`
- `image_url`
- `barcode`
- `buyer_assistant_vs`
- `buyer_vs`
- `full_composition`
- `size_type`
- `AML`

Columns:
| Column | Data type | Meaning | Nullable | Notes |
|---|---|---|---|---|
| `product_id` | TODO | Unique product identifier | TODO | Dictionary key used by other tables |
| `article` | TODO | Article | TODO | Multiple products can have the same article. Within one brand, products with the same article are the same product. For `bu = Fashion`, article is assembled from `style`, `fabric`, `color_code`, `common_size`, and `season_short`; for other BUs, article is provided by the manufacturer |
| `style` | TODO | Manufacturer article/style | TODO | Used in Fashion article assembly |
| `fabric` | TODO | Material code | TODO | Used in Fashion article assembly |
| `color_code` | TODO | Color code | TODO | Used in Fashion article assembly |
| `name` | TODO | Full product name | TODO | Product description |
| `breadcrumbs` | TODO | Product hierarchy path | TODO | Assembled from `bu`, `category`, `group`, and `product` |
| `bu` | TODO | First hierarchy level / business unit | TODO | Business direction |
| `category` | TODO | Second hierarchy level | TODO | Category |
| `group` | TODO | Third hierarchy level | TODO | Group |
| `subgroup` | TODO | Fourth hierarchy level | TODO | Subgroup |
| `product` | TODO | Fifth hierarchy level | TODO | Product type |
| `department` | TODO | Department | TODO | Product dimension |
| `subdepartment` | TODO | Subdepartment | TODO | Product dimension |
| `department_vs` | TODO | Viled Style department | TODO | Product dimension |
| `subdepartment_vs` | TODO | Viled Style subdepartment | TODO | Product dimension |
| `brand` | TODO | Product brand / mark | TODO | Product dimension |
| `season_year` | TODO | Fashion season year | TODO | Season attribute |
| `season_short` | TODO | Short season code | TODO | `SS` means Spring Summer; `FW` means Fall Winter |
| `season` | TODO | Full season name | TODO | Season attribute |
| `gender` | TODO | Gender | TODO | Product dimension |
| `sizechart_type` | TODO | Size chart type | TODO | Size attribute |
| `sizechart` | TODO | Size chart | TODO | Size attribute |
| `common_size` | TODO | Size | TODO | Used in Fashion article assembly |
| `italian_size` | TODO | Italian size | TODO | Size attribute |
| `color_eng` | TODO | Color in English | TODO | Color attribute |
| `color_rus` | TODO | Color in Russian | TODO | Color attribute |
| `country` | TODO | Manufacturer country | TODO | Product dimension |
| `buyer` | TODO | Buyer employee name | TODO | Procurement responsibility |
| `buyer_assistant` | TODO | Buyer assistant employee name | TODO | Procurement responsibility |
| `composition` | TODO | Product material/composition | TODO | Product attribute |
| `fur` | TODO | Fur indicator | TODO | Boolean true/false |
| `heel` | TODO | Heel height/type | TODO | Product attribute |
| `brand_category` | TODO | Brand category | TODO | Examples: `Люкс`, `Ниша`, `Товар без кода` |
| `individual_number` | TODO | Manufacturer individual product number | TODO | Product attribute |
| `consigment` | TODO | Consignment product indicator | TODO | Boolean true/false |
| `carryover` | TODO | Carryover indicator | TODO | Boolean true/false |
| `stock_year` | TODO | Year in which the product was ordered | TODO | Product attribute |
| `world_retail_price` | TODO | World retail price | TODO | Price attribute |
| `collection_jw` | TODO | Collection for J&W and H&G business directions | TODO | Product attribute |
| `store_jw` | TODO | Boutique | TODO | Product attribute |
| `volume` | TODO | Volume | TODO | Field is not used |
| `tone` | TODO | Tone | TODO | Field is not used |
| `line` | TODO | Brand line | TODO | Product attribute |
| `department_en` | TODO | Department in English | TODO | Product dimension |
| `url` | TODO | Product web store URL | TODO | Link |
| `image_url` | TODO | Product image URL | TODO | Link |
| `barcode` | TODO | Barcode | TODO | Example format: `2600000519588` |
| `buyer_assistant_vs` | TODO | Viled Style buyer assistant employee name | TODO | Procurement responsibility |
| `buyer_vs` | TODO | Viled Style buyer employee name | TODO | Procurement responsibility |
| `full_composition` | TODO | Full product composition and material parameters | TODO | Product attribute |
| `size_type` | TODO | Size type | TODO | Product size attribute |
| `AML` | TODO | AML indicator | TODO | Boolean true/false |

Relationships:
| From table | From column | To table | To column | Cardinality | Notes |
|---|---|---|---|---|---|
| `[LLM].[sales]` | `product_id` | `[DWH].[LLM].[dimension_product]` | `product_id` | Many-to-one expected | Product dictionary lookup |
| `[DWH].[LLM].[cost]` | `product_id` | `[DWH].[LLM].[dimension_product]` | `product_id` | Many-to-one expected | Product dictionary lookup |
| `[DWH].[LLM].[stock]` | `product_id` | `[DWH].[LLM].[dimension_product]` | `product_id` | Many-to-one expected | Product dictionary lookup |
| `[DWH].[LLM].[v_Purchases]` | `product_id` | `[DWH].[LLM].[dimension_product]` | `product_id` | Many-to-one expected | Product dictionary lookup |
| `[DWH].[LLM].[price]` | `ware_id` | `[DWH].[LLM].[dimension_product]` | `product_id` | Many-to-one expected | Confirmed mapping for product-attribute filters such as `article` |

Default sorting:
- Product dimension rows: `product_id ASC`.

Sample query:

```sql
SELECT TOP 100
    [product_id],
    [article],
    [name],
    [brand],
    [bu],
    [category],
    [season_short],
    [common_size],
    [barcode],
    [url],
    [image_url]
FROM [DWH].[LLM].[dimension_product]
ORDER BY [product_id] ASC;
```

Open questions:
- Confirm physical data types and nullability.
- Confirm whether every fact-table `product_id` always exists in `[DWH].[LLM].[dimension_product]`.

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

## Table: [DWH].[LLM].[stock]

Purpose:
Stores product stock movement operations, including warehouse transfers.

Grain:
One row per product movement operation line for a `product_id`, `warehouse_id`, document, and operation `date`.

Primary date column:
- `date`

Primary identifiers:
- `source_database`
- `recorder_guid`
- `document_id`
- `warehouse_id`
- `product_id`

Preferred columns:
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

Columns:
| Column | Data type | Meaning | Nullable | Notes |
|---|---|---|---|---|
| `source_database` | TODO | Source data system/database | TODO | Source dimension |
| `date` | datetime | Operation/document date, for example `2026-05-21 22:56:37.000` | TODO | Primary date column |
| `recorder_type` | TODO | Operation name | TODO | Examples: `ввод_остатков`, `Перемещение товаров`, `Поступление товаров и услуг`, `Реализация товаров и услуг`, `Списание товаров` |
| `recorder_type_guid` | TODO | Operation code for the `source_database` + `recorder_type` pair | TODO | Operation identifier |
| `recorder_guid` | TODO | 1C document identifier, for example `9d780050-5690-2ada-11f1-031b46aa02bf` | TODO | Same `recorder_guid` means one common 1C document |
| `warehouse_id` | TODO | Warehouse identifier | TODO | Warehouse dimension |
| `product_id` | TODO | Unique product code | TODO | Primary product identifier |
| `quantity` | TODO | Signed operation quantity | TODO | Positive means receipt to warehouse; negative means issue from warehouse |
| `amount` | TODO | Not used | TODO | Do not use for stock metrics |
| `document_id` | TODO | 1C document number, for example `УТVF0000549` | TODO | Use for transfer document number questions |
| `movement_index` | TODO | Product operation sequence number | TODO | Ordered chronologically by `date` from older to newer |

Default sorting:
- Latest/current movement rows: `date DESC`.
- Movement history/dynamics: `date ASC`.

Stock balance rules:
- Stock at the beginning of a period is `SUM(quantity)` for all operations before the calculation date.
- Stock at the end of a period is `SUM(quantity)` for all operations through and including the calculation date.
- For a period range, beginning balance uses `date < period_start`; ending balance uses `date <= period_end`.

Sample queries:

```sql
SELECT TOP 100
    [source_database],
    [date],
    [recorder_type],
    [recorder_type_guid],
    [recorder_guid],
    [warehouse_id],
    [product_id],
    [quantity],
    [amount],
    [document_id],
    [movement_index]
FROM [DWH].[LLM].[stock]
ORDER BY [date] DESC;
```

```sql
SELECT
    [warehouse_id],
    SUM(CASE WHEN [date] < '2025-03-01' THEN [quantity] ELSE 0 END) AS stock_quantity_start,
    SUM(CASE WHEN [date] <= '2025-03-31' THEN [quantity] ELSE 0 END) AS stock_quantity_end
FROM [DWH].[LLM].[stock]
GROUP BY [warehouse_id]
ORDER BY [warehouse_id];
```

Open questions:
- Confirm physical data types and nullability.
- Confirm whether `movement_index` is unique per `product_id` globally or per `source_database` + `product_id`.
- Confirm whether stock balances should usually be grouped by `warehouse_id`, `product_id`, or both when not specified.

## Table: [DWH].[LLM].[v_Purchases]

Purpose:
Stores purchase cost operation data for products.

Grain:
One row per purchase-related operation line for a `product_id`, source database, 1C document, division, and `purchase_date`.

Primary date column:
- `purchase_date`

Primary identifiers:
- `source_database`
- `recorder_number`
- `product_id`
- `division_id`

Preferred columns:
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

Columns:
| Column | Data type | Meaning | Nullable | Notes |
|---|---|---|---|---|
| `source_database` | TODO | Source database | TODO | Source dimension |
| `purchase_date` | date | Operation date, for example `2018-07-27` | TODO | Primary date column |
| `recorder_type` | TODO | Operation name | TODO | Allowed values: `Возврат товаров поставщику`, `ГТД по импорту`, `Поступление доп. расходов`, `Поступление товаров и услуг` |
| `recorder_number` | TODO | Document number in the 1C database | TODO | 1C document reference |
| `product_id` | TODO | Unique product identifier, Sprut code | TODO | Primary product identifier |
| `quantity` | TODO | Product quantity in the operation | TODO | Additive operation metric |
| `division_id` | TODO | Division code | TODO | Division dimension |
| `amount_kzt` | TODO | Full operation cost for the whole quantity in KZT | TODO | Additive currency metric; unit value is `amount_kzt / quantity` when `quantity <> 0` |
| `NDS_kzt` | TODO | VAT amount in KZT for the operation | TODO | Additive VAT metric |
| `amount_usd` | TODO | Full operation cost for the whole quantity in USD | TODO | Additive currency metric; unit value is `amount_usd / quantity` when `quantity <> 0` |
| `NDS_usd` | TODO | VAT amount in USD for the operation | TODO | Additive VAT metric |
| `amount_eur` | TODO | Full operation cost for the whole quantity in EUR | TODO | Additive currency metric; unit value is `amount_eur / quantity` when `quantity <> 0` |
| `NDS_eur` | TODO | VAT amount in EUR for the operation | TODO | Additive VAT metric |
| `amount_chf` | TODO | Full operation cost for the whole quantity in CHF | TODO | Additive currency metric; unit value is `amount_chf / quantity` when `quantity <> 0` |
| `NDS_chf` | TODO | VAT amount in CHF for the operation | TODO | Additive VAT metric |

Relationships:
| From table | From column | To table | To column | Cardinality | Notes |
|---|---|---|---|---|---|
| `[DWH].[LLM].[v_Purchases]` | `product_id` | `[DWH].[LLM].[dimension_product]` | `product_id` | Many-to-one expected | Product-dimension lookup for attribute filters |

Default sorting:
- Latest/current purchase rows: `purchase_date DESC`.
- Purchase history/dynamics: `purchase_date ASC`.

Sample queries:

```sql
SELECT TOP 100
    [source_database],
    [purchase_date],
    [recorder_type],
    [recorder_number],
    [product_id],
    [quantity],
    [division_id],
    [amount_kzt],
    [NDS_kzt],
    [amount_usd],
    [NDS_usd],
    [amount_eur],
    [NDS_eur],
    [amount_chf],
    [NDS_chf]
FROM [DWH].[LLM].[v_Purchases]
ORDER BY [purchase_date] DESC;
```

```sql
SELECT
    [product_id],
    SUM([amount_kzt]) AS purchase_amount_kzt,
    SUM([quantity]) AS purchase_quantity,
    SUM([amount_kzt]) / NULLIF(SUM([quantity]), 0) AS purchase_amount_kzt_per_unit
FROM [DWH].[LLM].[v_Purchases]
GROUP BY [product_id]
ORDER BY purchase_amount_kzt DESC;
```

Open questions:
- Confirm physical data types and nullability.
- Confirm whether `recorder_number` is unique only within `source_database`.
- Confirm whether returns to supplier should normally be included or excluded from purchase-cost totals.

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

## Table: [DWH].[LLM].[division]

Purpose:
Sales-point dimension containing stores, boutiques, points of sale, and their cities.

Grain:
One row per division / sales point.

Primary date column:
- none

Primary identifier:
- `id`

Preferred columns:
- `id`
- `division`
- `city`

Columns:
| Column | Data type | Meaning | Nullable | Notes |
|---|---|---|---|---|
| `id` | TODO | Unique division identifier | TODO | Join key |
| `division` | TODO | Division / store / boutique / sales-point name | TODO | Dimension attribute |
| `city` | TODO | City containing the sales point | TODO | Values include blank, Актобе, Алматы, Астана, Атырау, Перемещение |

Relationships:
| From table | From column | To table | To column | Cardinality | Notes |
|---|---|---|---|---|---|
| `[LLM].[sales]` | `division_id` | `[DWH].[LLM].[division]` | `id` | Many-to-one expected | Confirmed key mapping for store and city filters/grouping |

Use this dimension only for descriptive filtering and grouping. Do not aggregate `id`.

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
- `division_id`

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
| `division_id` | TODO | Division identifier | TODO | Joins `[DWH].[LLM].[division].[id]` |
| `quantity` | TODO | Quantity of sold product | TODO | Quantity metric |
| `amount` | TODO | Sale amount in KZT | TODO | Default sales amount metric |
| `amount_usd` | TODO | Sale amount in USD | TODO | Currency metric |
| `amount_eur` | TODO | Sale amount in EUR | TODO | Currency metric |

Relationships:
| From table | From column | To table | To column | Cardinality | Notes |
|---|---|---|---|---|---|
| `[LLM].[sales]` | `product_id` | TODO | TODO | TODO | Use for sales-by-product logic |
| `[LLM].[sales]` | `division_id` | `[DWH].[LLM].[division]` | `id` | Many-to-one expected | Store/city lookup |

Sample queries:

```sql
SELECT TOP 100
    [sale_date],
    [document_number],
    [product_id],
    [division_id],
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
