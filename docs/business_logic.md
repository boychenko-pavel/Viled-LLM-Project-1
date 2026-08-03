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
| Stock movements | `[DWH].[LLM].[stock]` | `date` | `product_id` | `quantity` for movements and stock balances |
| Purchases | `[DWH].[LLM].[v_Purchases]` | `purchase_date` | `product_id` | `amount_kzt` for money, `quantity` for units |
| Product dimension | `[DWH].[LLM].[dimension_product]` | none | `product_id` | count rows or show product attributes |
| Division dimension | `[DWH].[LLM].[division]` | none | `id` | count rows or show sales-point attributes |

## Division Dimension Logic

Use `[DWH].[LLM].[division]` as the sales-point dictionary for store, boutique, point-of-sale, division, and city requests.

| User wording | Column |
|---|---|
| магазин, бутик, точка продаж, подразделение | `division` |
| город | `city` |

- Join sales with `fact.division_id = div.id`.
- Apply store and city filters to `div.division` and `div.city`, respectively.
- Normalize known Russian, English, transliterated, and abbreviated store names
  to the exact `div.division` value using `sql_agent/division_aliases.py`.
  For example, `сакс`, `Saks`, and `сакс фифт авеню` mean
  `Saks Fifth Avenue` when used in store/division context.
- Group sales by `div.division` or `div.city` when requested.
- Treat `id`, `division`, and `city` as descriptive attributes, not additive metrics.
- No relationship to price, cost, stock, or purchases is confirmed; do not join those tables to this dimension.

## Product Dimension Logic

Use `[DWH].[LLM].[dimension_product]` when the user asks about:
- product master data / product dictionary;
- product attributes, карточка товара, номенклатура;
- article, brand, category, BU, hierarchy, season, gender, size, color, barcode, buyer, URL, image URL, composition, AML, carryover, consignment, or similar product attributes.

Business vocabulary:
| User wording | Meaning | Column/table |
|---|---|---|
| product dictionary, справочник товаров, номенклатура | Product master table | `[DWH].[LLM].[dimension_product]` |
| product_id, код спрута | Unique product identifier | `product_id` |
| article, артикул | Product article | `article` |
| style | Manufacturer article/style | `style` |
| fabric | Material code | `fabric` |
| color_code | Color code | `color_code` |
| brand, бренд, марка | Product brand | `brand` |
| bu, business unit | First hierarchy level / business unit | `bu` |
| ювелирка, ювелирное направление, JW, J&W | Jewelry and watches business unit | `bu = 'J&W'` |
| category, group, subgroup, product | Product hierarchy levels | `category`, `group`, `subgroup`, `product` |
| breadcrumbs | Hierarchy path | `breadcrumbs` |
| season_short, season_year, season | Fashion season attributes | `season_short`, `season_year`, `season` |
| gender, пол | Gender | `gender` |
| common_size, italian_size, sizechart | Size attributes | `common_size`, `italian_size`, `sizechart` |
| color_eng, color_rus | Product color | `color_eng`, `color_rus` |
| barcode, штрихкод | Barcode | `barcode` |
| buyer, buyer_assistant | Buyer and buyer assistant | `buyer`, `buyer_assistant` |
| url, image_url | Product and image links | `url`, `image_url` |

Default behavior:
- For row requests, show product attributes from `[DWH].[LLM].[dimension_product]` and use `TOP 100` unless the user asks otherwise.
- For previews and samples, use `TOP 10`.
- For all data / all columns requests, select all known product dimension columns.
- Sort product dimension rows by `product_id ASC` by default.
- Use `COUNT(*)` for "how many products" questions.
- Group by attributes such as `brand`, `bu`, `category`, `season_short`, `gender`, `common_size`, or `buyer` when the user asks "by ..." / "по ...".

Article rules:
- Several products can have one `article`.
- If products inside one `brand` have the same `article`, they are the same product.
- For `bu = Fashion`, `article` is assembled as `style + ' ' + fabric + '.' + color_code + '_' + common_size + '_' + last two symbols from season_short + season suffix`.
- Fashion season suffix: use `1` when `season_short` contains `SS`; use `2` when `season_short` contains `FW`.
- Example Fashion article: `807321 Y7I21.2568_38_251`.
- For other `bu` values, `article` is provided by the manufacturer.

Season rules:
- `season_short` beginning with `SS` means Spring Summer / Весна-лето.
- `season_short` beginning with `FW` means Fall Winter / Осень-зима.
- SS seasons run from March 1 through the end of August.
- FW seasons run from September 1 through the end of February.

Do not:
- Do not use product dimension columns as additive facts or financial metrics, except simple counts of rows/products.

Filtering value tables:
- Treat price, sales, cost, stock, and purchases as value/fact tables.
- If a value-table request contains a product attribute such as article, BU/business direction, collection, brand, category, season, size, color, barcode, buyer, or another documented dimension column, join `dimension_product` and apply that attribute as a filter.
- For such product-dimension filters, first build a `product_scope` CTE from
  `dimension_product`, apply the filter inside the CTE, and join the fact table
  to `product_scope` before aggregation, `ROW_NUMBER()`, sorting, or final row
  selection. Do not add `product_scope` when no product-dimension filter exists.
- Join sales, cost, stock, and purchases on `fact.product_id = dim.product_id`.
- Join retail prices on `fact.ware_id = dim.product_id`.
- Outside the documented GM calculation, do not silently reduce a request that
  names two fact domains to one table. Require clarification because the
  cross-fact grain and join rules are not confirmed.

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
- "Все данные" means all known columns with the web-safe `TOP 100`; requested
  filters must still be applied. Unlimited output requires pagination or export.
- "Последние N цен" means `TOP N ... ORDER BY price_date DESC`; do not collapse
  the result to only `_RANK = 1` unless one current price was requested.

Clarification rules:
- TODO

Do not:
- Do not use `[DWH].[LLM].[price]` for sales, sold quantity, revenue, or sale documents.
- Do not assume `ware_id` is equal to `[LLM].[sales].[product_id]` unless the mapping is confirmed.

## Gross Margin Logic

Use the deterministic GM calculation for `GM`, `Gross Margin`, `ГМ`,
`маржинальность`, and `маржа`.

- Calculate GM in KZT for every individual Sprut code (`product_id`), including
  requests filtered or grouped by `article` or `brand`.
- Join `[DWH].[LLM].[price].[ware_id]`,
  `[DWH].[LLM].[stock].[product_id]`, `[DWH].[LLM].[cost].[product_id]`, and
  `[DWH].[LLM].[dimension_product].[product_id]` as the same Sprut product code
  for this calculation.
- For an `article`, `brand`, `product_id`, or another product-dimension filter,
  first build a `product_scope` CTE from
  `[DWH].[LLM].[dimension_product]`. Apply the dimension filter inside that CTE,
  then join `product_scope` to `stock`, `price`, and `cost` before stock
  aggregation or price/cost `ROW_NUMBER()` calculations. Do not apply the
  product-dimension filter only in the final `SELECT`.
- Do not filter products by stock availability by default.
- If the request explicitly says `в наличии` or `на остатках`, include only
  products whose current stock is positive:
  `SUM([DWH].[LLM].[stock].[quantity]) > 0`.
- Use the latest effective KZT retail price per product, ordered by
  `price_date DESC` and restricted to `price_date <= calculation time`.
- Retail prices include VAT. Remove 16% VAT as
  `full_retail_price_kzt / 1.16`.
- If a discount is requested, apply it to the VAT-inclusive retail price first,
  then remove VAT from the discounted price. Keep
  `retail_price_kzt_incl_vat` as the discounted VAT-inclusive price and append
  `retail_price_kzt_before_discount`, `discount_percent`, and
  `retail_price_kzt_after_discount` after the mandatory GM columns.
- Use the current average unit cost from the latest cost balance row:
  `cost_sum / NULLIF(qnt_sum, 0)`.
- `gross_margin_kzt = retail_price_kzt_vat_excluded - unit_cost_kzt`.
- `gross_margin_percent = gross_margin_kzt / NULLIF(retail_price_kzt_vat_excluded, 0) * 100`.
- Return the mandatory report columns in this order: `остаток`, `product_id`,
  `article`, `brand`, `name`, `price_date`, `cost_date`,
  `retail_price_kzt_incl_vat`, `retail_price_kzt_excl_vat`,
  `cost_kzt_per_unit`, `gross_profit_kzt_per_unit`, and
  `gross_margin_percent`.
- Keep the web-chat detailed-row safety limit of 100 rows.
- For top/highest/lowest GM requests, sort by `gross_margin_percent` in the
  requested direction before applying `TOP`; never rank by `product_id`.
- Reject an explicitly supplied discount outside `0..100%` instead of silently
  calculating GM without the discount.

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
- For every aggregate sales report, include all applicable additive totals:
  `SUM(quantity)`, `SUM(full_price)`, `SUM(amount)`, `SUM(loan)`,
  `SUM(cash)`, `SUM(card)`, `SUM(certificate)`, `SUM(bonus)`, and
  `SUM(discount)`.
  Keep the requested metric as the primary metric and do not duplicate it.
- Append an `ИТОГО` row to grouped sales reports. Calculate it over the full
  filtered set before applying the grouped display limit.
- For detailed sales requests, return only `sale_date`, `document_number`,
  `product_id`, `brand`, `article`, `individual_number`, `name`, `quantity`,
  `full_price`, `price`, `amount`, `loan`, `cash`, `card`, `certificate`, `bonus`,
  `discount`, `channel`, `payment_method`, `partner_id`, and `customer_status`.
  Read the four product attributes from `[DWH].[LLM].[dimension_product]`.
- Add a final `ИТОГО` row to detailed sales results with totals for `quantity`,
  `full_price`, `amount`, `loan`, `cash`, `card`, `certificate`, `bonus`, and
  `discount`. Do not sum `price`. Calculate these totals over the full
  filtered result before applying the 100-row display limit.
- For sales-by-product questions, group by `product_id`.
- For sales-by-date questions, group by or filter on `sale_date`.
- "How many brands/articles/categories/channels/payment methods/products" means
  `COUNT(DISTINCT <attribute>)`. Preserve an additional requested `GROUP BY`
  and calculate the `ИТОГО` distinct count over the full filtered set, not as
  a sum of per-group distinct counts.

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

Current and average cost rules:

- Current average unit cost is the ratio from the latest balance row per
  `product_id`: `cost_sum / NULLIF(qnt_sum, 0)`.
- An explicitly chosen unweighted operation average uses `AVG(cost_per_unit)`.
- A weighted operation average uses
  `SUM(cost) / NULLIF(SUM(quantity), 0)`.
- Never use `AVG(cost)` for average unit cost: `cost` is the full operation cost.
- "Последние N операций себестоимости" returns N history rows ordered by
  `date DESC`, not one current balance row.

Default behavior:
- Monetary values are in KZT.
- For operation totals, aggregate `SUM(cost)`; for operation quantities, aggregate `SUM(quantity)`.
- `qnt_sum` and `cost_sum` are running balances. Never sum them across operation rows.
- For the latest/current balance, use the latest row by `date` for each required
  `product_id`. Partition only by `product_id`; do not include `db`, even when
  the same product occurs under several `db` values.
- For latest records, sort by `date DESC`; for history/dynamics, sort by `date ASC`.
- For detailed rows, use `TOP 100`; for previews, use `TOP 10`.
- For "какая себестоимость товара <product_id>", show `date`, `product_id`, `op_type`, `quantity`, `cost`, `cost_per_unit`, `qnt_sum`, and `cost_sum`, ordered by `date DESC`, with the web-safe `TOP 100`.

Clarification rules:
- If “общая себестоимость” could mean transaction turnover (`SUM(cost)`) or the current inventory balance (`cost_sum`), ask which meaning is intended.

Do not:
- Do not use the retail price columns from `[DWH].[LLM].[price]` as cost.
- Do not calculate revenue or sales from `[DWH].[LLM].[cost]`.
- Do not aggregate `qnt_sum` or `cost_sum` with `SUM` across operation rows.
- Do not join the table to sales or prices until join keys and grain are confirmed.

## Stock Movement Logic

Use `[DWH].[LLM].[stock]` when the user asks about:
- product stock balances;
- warehouse stock movements;
- operations with `Перемещение товаров`;
- transfer document numbers / 1C document numbers;
- explicit references to `DWH.LLM.stock`.

Business vocabulary:
| User wording | Meaning | Column/table |
|---|---|---|
| остаток, stock balance | Stock quantity balance | `SUM([quantity])` from `[DWH].[LLM].[stock]` |
| перемещение товаров | Warehouse transfer operation | `recorder_type = 'Перемещение товаров'` when explicitly requested as a filter |
| склад, warehouse | Warehouse identifier | `warehouse_id` |
| товар, product | Product identifier | `product_id` |
| номер документа, документ в 1С | 1C document number | `document_id` |
| идентификатор документа | 1C document GUID | `recorder_guid` |
| операция, тип операции | Movement operation name | `recorder_type` |
| источник, база 1С | Source database | `source_database` |

Default behavior:
- Show movement rows with `source_database`, `date`, `recorder_type`, `recorder_type_guid`, `recorder_guid`, `warehouse_id`, `product_id`, `quantity`, `amount`, `document_id`, and `movement_index`.
- `quantity > 0` means receipt to a warehouse; `quantity < 0` means issue from a warehouse.
- `amount` is not used for stock logic.
- Latest/current movement rows sort by `date DESC`; history/dynamics sort by `date ASC`.
- For detailed rows, use `TOP 100`; for previews, use `TOP 10`.

Stock balance rules:
- Beginning balance: `SUM(quantity)` for operations before the calculation date.
- Ending balance: `SUM(quantity)` for operations through and including the calculation date.
- For a period, beginning balance uses `date < period_start`. Because `date` is
  `datetime`, the inclusive ending balance is implemented as
  `date < DATEADD(day, 1, period_end)` so all operations on the final day are included.
- Group by `product_id` or `warehouse_id` only when the user asks for that breakdown.

Do not:
- Do not use `[DWH].[LLM].[cost].[qnt_sum]` for warehouse movement questions.
- Do not use `[DWH].[LLM].[stock].[amount]` as a financial metric.
- Do not join stock to sales, prices, or cost until join grain is confirmed.

## Purchase Logic

Use `[DWH].[LLM].[v_Purchases]` when the user asks about:
- purchase cost / закупочная стоимость;
- purchases or procurement;
- supplier returns;
- import declarations / `ГТД по импорту`;
- additional purchase expenses;
- purchase receipts / `Поступление товаров и услуг`;
- purchase VAT / НДС по закупкам.

Business vocabulary:
| User wording | Meaning | Column/table |
|---|---|---|
| закупка, закупочная стоимость, purchase cost, procurement | Purchase operation cost | `[DWH].[LLM].[v_Purchases]` |
| товар, product | Product identifier | `product_id` |
| дата закупки, дата операции | Purchase operation date | `purchase_date` |
| документ, номер документа, 1C document | 1C document number | `recorder_number` |
| операция, тип операции | Purchase operation name | `recorder_type` |
| подразделение, division | Division code | `division_id` |
| количество, quantity | Operation quantity | `quantity` |
| KZT, тенге | Purchase amount in KZT | `amount_kzt` |
| USD, доллар | Purchase amount in USD | `amount_usd` |
| EUR, евро | Purchase amount in EUR | `amount_eur` |
| CHF, франк | Purchase amount in CHF | `amount_chf` |
| НДС | VAT amount; KZT by default unless currency is specified | `NDS_kzt`, `NDS_usd`, `NDS_eur`, `NDS_chf` |

Default behavior:
- For money totals without currency, use `SUM(amount_kzt)`.
- For USD totals, use `SUM(amount_usd)`.
- For EUR totals, use `SUM(amount_eur)`.
- For CHF totals, use `SUM(amount_chf)`.
- For VAT without currency, use `SUM(NDS_kzt)`.
- For quantity totals, use `SUM(quantity)`.
- For purchase rows, show `source_database`, `purchase_date`, `recorder_type`, `recorder_number`, `product_id`, `quantity`, `division_id`, amount and VAT columns in KZT, USD, EUR, and CHF.
- For latest/current purchase rows, sort by `purchase_date DESC`; for history/dynamics, sort by `purchase_date ASC`.
- For detailed rows, use `TOP 100`; for previews, use `TOP 10`.

Unit cost rules:
- `amount_kzt / quantity` is purchase cost per unit in KZT when `quantity <> 0`.
- `amount_usd / quantity`, `amount_eur / quantity`, and `amount_chf / quantity` follow the same rule for their currencies.
- When calculating unit cost in SQL, use `NULLIF(quantity, 0)` or aggregate as `SUM(amount_*) / NULLIF(SUM(quantity), 0)`.

Allowed `recorder_type` values:
- `Возврат товаров поставщику`
- `ГТД по импорту`
- `Поступление доп. расходов`
- `Поступление товаров и услуг`

Do not:
- Do not use `[DWH].[LLM].[cost]` for purchase document questions when the user asks specifically about закупки / purchases.
- Do not join purchases to sales, stock, price, or cost until join grain is confirmed.

## Query Safety and Parsing Logic

- Preserve the order of explicit date boundaries. Reject a reversed range
  instead of swapping it silently. A day written as `15 марта 2026` is one
  exact date, not the whole month. `после/позже` is strict, `не ранее` is
  inclusive, and `раньше` excludes the named day.
- Do not apply only one side of a two-sided numeric range. Until two threshold
  bounds are represented in the structured intent, ask for one threshold.
- An explicitly named unsupported currency requires clarification; default
  KZT/all-currency behavior applies only when no currency is specified.
- Treat the local-LLM fallback payload as untrusted structured input.
  Canonicalize its table from the domain and validate operations, numeric
  aggregate metrics, running-balance rules, joins, filters, dates, sorting,
  and limits before building SQL.
- Raw web-chat SQL must remain one bounded read-only `SELECT`. Block
  side-effect statements, pass-through sources such as `OPENQUERY` and
  `OPENROWSET`, and unbounded nested/window payloads.
- In addition to row limits, stop materializing a web result when one cell is
  larger than 512 KiB or the estimated result payload exceeds 5 MiB. Use
  pagination or file export for larger results.

## Cross-Table Logic

Document confirmed joins here before relying on them in SQL generation.

Relationships:
| Business question | Tables | Join keys | Required pre-aggregation | Notes |
|---|---|---|---|---|
| TODO | TODO | TODO | TODO | TODO |

Potential relationships requiring confirmation:
- `[DWH].[LLM].[cost].[product_id]` to `[LLM].[sales].[product_id]`.
- `[DWH].[LLM].[cost].[product_id]` to `[DWH].[LLM].[price].[ware_id]`.
- `[DWH].[LLM].[stock].[product_id]` to `[LLM].[sales].[product_id]` or `[DWH].[LLM].[cost].[product_id]`.
- `[DWH].[LLM].[v_Purchases].[product_id]` to sales, stock, cost, or price product identifiers.
- `[DWH].[LLM].[price].[ware_id]` to `[DWH].[LLM].[dimension_product].[product_id]`.

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
