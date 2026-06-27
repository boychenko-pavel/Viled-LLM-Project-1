"""
price_corr — flag products under the same article that have different retail prices.

Key change vs. previous version
-------------------------------
Comparison is now correct PAIRWISE.  For every article, every pair of products
with DIFFERENT retail_price is emitted exactly once (no self-pairs, no mirror
duplicates).  Same-price pairs are dropped.

    art1 / prod1 / 100
    art1 / prod2 / 200
    art1 / prod3 / 100

    -> emitted: (prod1,prod2)=100/200 and (prod2,prod3)=200/100
    -> skipped: (prod1,prod3)=100/100
"""

import re
import datetime as dt
from pathlib import Path

import pandas as pd
import pyodbc

from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.application import MIMEApplication

from prefect import flow, task
from prefect_email import EmailServerCredentials, email_send_message
from prefect.blocks.system import Secret


# ─────────────────────────── CONFIG ─────────────────────────────────────────
FILE_PATH         = r"/home/admin1/prefect_prod/price_corr/check_"
HOST              = "192.168.100.9"
DRIVER            = "{ODBC Driver 17 for SQL Server}"
DB_NAME           = "DWH"
CHOPARD_REF_FILE  = Path(r"/home/admin1/prefect_prod/price_corr/справочник Chopard.xlsx")
CARTIER_TRANSITION_FILE = Path(r"/home/admin1/prefect_prod/price_corr/Версии артикулов для PowerBI. Cartier - new article values v.2026-05-15.xlsx")
CARTIER_PRICES_FILE     = Path("prices_cartier.xlsx")
CARTIER_EXCLUDE_FILE    = Path("cartier_exclude_articles.xlsx")
VCA_EXCLUDE_FILE        = Path(r"/home/admin1/prefect_prod/price_corr/Исключения из Выравнивания цен VCA 2026-05-29.xlsx")
BRAND_MANAGER_FILE      = Path("brand_manager.xlsx")

# Secrets are resolved lazily inside get_conn so the module can be imported
# without hitting Prefect blocks at import time.
def _conn_string() -> str:
    user     = Secret.load("user").get()
    password = Secret.load("password").get()
    return (f"DRIVER={DRIVER};SERVER={HOST};DATABASE={DB_NAME};"
            f"UID={user};PWD={password}")


def get_conn():
    """Always returns a NEW connection.  Caller is responsible for closing
    (use `with get_conn() as conn:`)."""
    return pyodbc.connect(_conn_string())


# Table names that get_sql_table is allowed to read.  Prevents SQL injection
# even though the caller is internal.
_ALLOWED_TABLES = {
    "Dimension.v_product_v2",
    "Dimension.Division",
    "Dimension.Warehouse",
    "Dimension.RetailPrice",
    "Fact.stock",
}


def save_excel(res: pd.DataFrame, file_path: str) -> bool:
    res.to_excel(file_path, index=False)
    return True


# ────────────────── SQL HELPERS ─────────────────────────────────────────────
@task
def get_sql_table(table_name: str, conn) -> pd.DataFrame:
    """Read an entire dimension/fact table.  table_name is validated against
    an allow-list."""
    if table_name not in _ALLOWED_TABLES:
        raise ValueError(f"Table {table_name!r} is not in the allow-list")
    # Quoted identifier prevents the f-string from being a real injection path.
    return pd.read_sql_query(f"SELECT * FROM {table_name}", conn)


# ───────────────── CARTIER ARTICLE-TRANSITION FILE ──────────────────────────
def prepare_cartier_transition(
    src_file: Path = CARTIER_TRANSITION_FILE,
    sheet: str = "Лист1",
) -> pd.DataFrame:
    df = (
        pd.read_excel(src_file, sheet_name=sheet, dtype=str)[["Старый", "Новый"]]
        .apply(lambda col: col.astype(str)
                              .str.strip()
                              .str.replace(r"\s+", " ", regex=True))
    )

    identical = df["Старый"] == df["Новый"]
    blank_old = df["Старый"].str.lower().isin(["", "nan"])
    blank_new = df["Новый"].str.lower().isin(["", "nan"])
    nan_new   = df["Новый"].isna()
    special_chars = re.compile(r"[-'\".,]")
    special   = df.apply(lambda col: col.str.contains(special_chars)).any(axis=1)

    df = df.loc[~(identical | blank_old | blank_new | nan_new | special)].copy()

    def shorten(text: str) -> str:
        if len(text) <= 12:
            return text
        m = re.search(r"\bCR\S*", text, flags=re.IGNORECASE)
        return m.group(0) if m else text

    def strip_cr_prefix(text: str) -> str:
        return text[2:] if text.upper().startswith("CR") else text

    # .map per column replaces deprecated .applymap
    for col in ("Старый", "Новый"):
        df[col] = df[col].map(shorten).map(strip_cr_prefix)

    same_len = df["Старый"].str.len() == df["Новый"].str.len()
    df = df.loc[same_len].copy()

    old_values = set(df["Старый"])
    df["repeated"] = df["Новый"].isin(old_values).map({True: "yes", False: "no"})

    df = (df.assign(_yesfirst=df["repeated"].eq("yes").astype(int))
            .sort_values("_yesfirst", ascending=False)
            .drop(columns="_yesfirst")
            .reset_index(drop=True))

    return df.rename(columns={"Старый": "old", "Новый": "new"})


cartier_transition = prepare_cartier_transition()


# ─────────────────── CORRECTIONS ────────────────────────────────────────────
@task
def products_corrections(products: pd.DataFrame) -> pd.DataFrame:
    # products = products.rename(columns={"id": "product_id"}).copy()
    products["product_id"] = (products["product_id"].astype(str)
                                                    .str.strip()
                                                    .str.replace(" ", "", regex=False))

    fashion_depts = (
        "Отдел детской одежды|Мужской отдел|"
        "Отдел женской обуви & аксессуаров|Отдел женской одежды|"
        "Viled Style Kids|Viled Style Men|Brunello Cucinelli Almaty|"
        "Loro Piana Almaty|Gucci Almaty|Viled Style Women|Kiton Nur-Sultan|"
        "Dolce&Gabbana Almaty|Viled Style Shoes&Accessories department|"
        "Loro Piana Nur-Sultan|Dolce&Gabbana Nur-Sultan|"
        "Saint Laurent Almaty|Valentino Almaty"
    )
    dept = products["department"].fillna("")
    products.loc[dept.str.contains(fashion_depts, regex=True), "bu"] = "Fashion"
    products.loc[dept.str.contains("Парфюмерия и Косметика"),  "bu"] = "Beauty"
    products.loc[dept.str.contains("Ювелирно-часовой"),         "bu"] = "J&W"
    products.loc[dept.str.contains("Товары для дома и подарки"),"bu"] = "H&G"
    return products


@task
def stock_corrections(stock: pd.DataFrame, products: pd.DataFrame) -> pd.DataFrame:
    cols = ["product_id", "department", "subdepartment", "department_vs",
            "subdepartment_vs", "brand", "category", "group", "product",
            "color_eng", "common_size", "gender", "season_short", "name",
            "article", "bu"]
    return stock.merge(products[cols], on="product_id", how="left")


@task
def purchases_corrections(purchases: pd.DataFrame) -> pd.DataFrame:
    p = purchases.copy()
    # Match original behavior: just divide. Zeros produce inf which is filtered
    # out naturally downstream. Avoid pd.NA — it triggers a known recursion bug
    # in pandas 1.x dtype resolution when mixed into numeric ops.
    qty = p["quantity"]
    for ccy in ("kzt", "eur", "usd", "chf"):
        p[f"last_buying_price_{ccy}"] = p[f"amount_{ccy}"] / qty
    return p[["product_id",
             "last_buying_price_kzt", "last_buying_price_eur",
             "last_buying_price_usd", "last_buying_price_chf"]]


# ───────────── HELPERS SHARED BETWEEN p_cor / vca_cartier / chopard ─────────
def _attach_division(stockname: pd.DataFrame, divname: pd.DataFrame) -> pd.DataFrame:
    out = stockname.merge(
        divname[["id", "division"]].rename(columns={"id": "division_id"}),
        on="division_id", how="left",
    )
    out["division_id"] = out["division_id"].fillna(0)
    return out
 
 
def _stock_qty_per_product_division(stock: pd.DataFrame,
                                    stockname: pd.DataFrame,
                                    by) -> pd.DataFrame:
    """Total stock qty per (product_id, <by>), excluding 'stock j&w' and
    'выставка' warehouses."""
    wh = stockname[["warehouse_id", "division_id", "name"]].rename(
        columns={"name": "warehouse_name"})
    merged = stock.merge(wh, on="warehouse_id", how="left")
    wn = merged["warehouse_name"].str.lower()
    keep = ~(wn.eq("stock j&w") | wn.str.contains("выставка", na=False))
    merged = merged.loc[keep]
    return merged.groupby(by, as_index=False).agg(quantity=("quantity", "sum"))
 
 
def _build_pairs_within_article(rp: pd.DataFrame,
                                products: pd.DataFrame,
                                purchases: pd.DataFrame,
                                group_key: str = "article") -> pd.DataFrame:
    """
    Self-merge `rp` on `group_key` and return all UNORDERED pairs
    (product_id, product_id_last) where the two products have DIFFERENT
    full_retail_price.  Each pair appears exactly once (lexicographic order
    on product_id) and self-pairs (A,A) are excluded.
 
    The returned frame mirrors the column shape the previous code produced:
    every original column from `rp` plus a `_last` counterpart, plus the
    purchase columns merged in for both sides.
    """
    if rp.empty:
        return rp.iloc[0:0].copy()
 
    rp = rp.copy()
    rp["full_article"] = rp["article"]
 
    # dwh_article = the ORIGINAL untouched DB article ("Артикул 1C"), before any
    # trim or mapping. The Cartier branch sets it explicitly (pre-mapping); the
    # other branches don't, so capture it here from `article` as a fallback.
    # (This fallback only triggers when a branch hasn't already set it; those
    # branches set dwh_article *before* their trim, so it stays original.)
    if "dwh_article" not in rp.columns:
        rp["dwh_article"] = rp["article"]
 
    # Max retail price WITHIN the pairing group (article, or Группа for Chopard
    # PATH A). Computed across all eligible products in the group BEFORE the
    # self-merge, so both sides of every pair naturally show the same value.
    rp["max_price_in_group"] = (
        rp.groupby(group_key)["full_retail_price"].transform("max")
    )
 
    # Right side gets *_last on every column we'll display.
    # IMPORTANT: full_article must be carried through here so the "2"-side
    # value reflects the SAME transformations (Cartier transition mapping +
    # [:-2] trim) as the "1"-side.  Pulling it from raw `products` later
    # would give the untransformed DB article.
    last_cols = {
        "product_id":         "product_id_last",
        "full_retail_price":  "full_retail_price_last",
        "division":           "division_last",
        "full_article":       "full_article_last",
        "price_date":         "price_date_last",
        "dwh_article":        "dwh_article_last",
    }
    right = rp[[group_key, *last_cols.keys()]].rename(columns=last_cols)
 
    paired = rp.merge(right, on=group_key, how="inner")
 
    # Drop self-pairs and mirror duplicates: keep only (A,B) where A < B.
    paired = paired.loc[
        paired["product_id"].astype(str) < paired["product_id_last"].astype(str)
    ].copy()
 
    # Different price = report it.
    paired = paired.loc[
        paired["full_retail_price"] != paired["full_retail_price_last"]
    ].copy()
 
    if paired.empty:
        return paired
 
    # Attach product_last details. NOTE: `article` is deliberately excluded
    # here — we already have full_article_last from the self-merge above,
    # which carries the trim/mapping. Pulling raw `article` from `products`
    # would overwrite that with the untransformed DB value.
    prod_last = (products[["product_id", "product",
                           "individual_number", "consigment", "name"]]
                 .rename(columns={
                     "product_id":        "product_id_last",
                     "product":           "product_last",
                     "individual_number": "individual_number_last",
                     "consigment":        "consigment_last",
                     "name":              "name_last",
                 }))
    paired = paired.merge(prod_last, on="product_id_last", how="left")
 
    # Only emit pairs where the product *type* matches (Ring vs Ring, etc.)
    paired = paired.loc[paired["product"] == paired["product_last"]].copy()
 
    # Attach purchase prices for both sides
    paired = paired.merge(purchases, on="product_id", how="left")
    paired = paired.merge(
        purchases.rename(columns={
            "product_id":            "product_id_last",
            "last_buying_price_kzt": "last_buying_price_kzt_last",
            "last_buying_price_usd": "last_buying_price_usd_last",
            "last_buying_price_eur": "last_buying_price_eur_last",
            "last_buying_price_chf": "last_buying_price_chf_last",
        }),
        on="product_id_last", how="left",
    )
    return paired
 
 
# ─────────────────── MAIN PRICE-CORRECTION TASK ─────────────────────────────
@task
def p_cor(products, stock, retail_price, purchases, divname, stockname):
    stockname = _attach_division(stockname, divname)
    rp = (retail_price
          .rename(columns={"ware_id": "product_id"})
          .merge(divname[["id", "division"]].rename(columns={"id": "division_id"}),
                 on="division_id", how="left"))
 
    rp = rp.merge(
        products[["product_id", "bu", "brand", "article", "individual_number",
                  "category", "group", "consigment", "product", "name"]],
        on="product_id", how="left",
    )
 
    # Tiffany: dedupe by product_id only; non-Tiffany: by (product_id, division)
    is_tiffany = rp["brand"].fillna("").str.contains("Tiffany")
    rp_tif  = rp.loc[is_tiffany].drop_duplicates(["product_id"], keep="last")
    rp_other = rp.loc[~is_tiffany].drop_duplicates(["product_id", "division"], keep="last")
 
    qty_pid       = _stock_qty_per_product_division(stock, stockname, ["product_id"])
    qty_pid_div   = _stock_qty_per_product_division(stock, stockname, ["product_id", "division_id"])
 
    rp_tif   = rp_tif.merge(qty_pid, on=["product_id"], how="left")
    rp_other = rp_other.merge(qty_pid_div, on=["product_id", "division_id"], how="left")
 
    rp = pd.concat([rp_other, rp_tif], sort=False)
 
    rp = rp.loc[
        (rp["quantity"] > 0)
        & rp["bu"].notna()
        & (
            rp["category"].isin(["Jewelry", "Watches"])
            | ((rp["bu"] == "H&G")
               & rp["category"].isin(["Home Decor", "Lighting", "Perfumerie H",
                                      "Tableware", "Textile", "Watches H"]))
        )
        & (rp["consigment"] == False)
        & rp["brand"].notna()
        & ~rp["brand"].isin(["Van Cleef & Arpels", "Cartier"])
        & ~rp["brand"].fillna("").str.contains("Chopard")
        & rp["article"].notna()
    ].copy()
 
    # Capture original DB article ("Артикул 1C") before any trim.
    rp["dwh_article"] = rp["article"]
 
    # Boucheron rings: trim last 2 chars of article (only if long enough,
    # so we never blank a short article)
    mask = (rp["brand"].fillna("").str.contains("Boucheron")
            & rp["product"].isin(["Ring", "Wedding ring"])
            & (rp["article"].astype(str).str.len() > 2))
    rp.loc[mask, "article"] = rp.loc[mask, "article"].astype(str).str[:-2]
 
    rp["division"] = rp["division"].fillna("no_division")
 
    return _build_pairs_within_article(rp, products, purchases, group_key="article")
 
 
# ─────────────────── CHOPARD ────────────────────────────────────────────────
@task
def p_cor_chopard(products, stock, retail_price, purchases, divname, stockname):
    stockname = _attach_division(stockname, divname)
    rp = (retail_price
          .rename(columns={"ware_id": "product_id"})
          .merge(divname[["id", "division"]].rename(columns={"id": "division_id"}),
                 on="division_id", how="left"))
    rp = rp.drop_duplicates(["product_id", "division"], keep="last")
 
    qty = _stock_qty_per_product_division(stock, stockname, ["product_id", "division_id"])
    rp = rp.merge(qty, on=["product_id", "division_id"], how="left")
    rp = rp.merge(
        products[["product_id", "bu", "brand", "article", "individual_number",
                  "category", "group", "consigment", "product", "name"]],
        on="product_id", how="left",
    )
 
    rp = rp.loc[
        (rp["quantity"] > 0)
        & rp["bu"].notna()
        & rp["category"].isin(["Jewelry", "Watches"])
        & (rp["consigment"] == False)
        & rp["brand"].fillna("").str.contains("Chopard")
        & rp["article"].notna()
    ].copy()
 
    ref = pd.read_excel(CHOPARD_REF_FILE, sheet_name="справочник", dtype=str)
    ref = ref[["article Viled 2", "Группа"]].dropna(subset=["article Viled 2"])
    ref["article Viled 2"] = ref["article Viled 2"].str.strip()
    ref["Группа"]          = ref["Группа"].str.strip()
 
    # Capture original DB article ("Артикул 1C") before the strip below.
    rp["dwh_article"] = rp["article"]
 
    rp["article"]  = rp["article"].astype(str).str.strip()
    rp["division"] = rp["division"].fillna("no_division")
 
    in_ref = rp["article"].isin(ref["article Viled 2"])
    rp_ref = rp.loc[in_ref].copy()
    rp_old = rp.loc[~in_ref].copy()
 
    results = []
 
    # PATH A — articles in reference: pair within Группа
    if not rp_ref.empty:
        rp_ref = rp_ref.merge(ref, left_on="article", right_on="article Viled 2", how="left")
        results.append(_build_pairs_within_article(
            rp_ref, products, purchases, group_key="Группа"))
 
    # PATH B — fallback: pair within article
    if not rp_old.empty:
        results.append(_build_pairs_within_article(
            rp_old, products, purchases, group_key="article"))
 
    if not results:
        return pd.DataFrame()
    return pd.concat(results, sort=False).reset_index(drop=True)
 
 
# ─────────────────── VAN CLEEF & ARPELS / CARTIER ───────────────────────────
@task
def p_cor_vca_cartier(products, stock, retail_price, purchases, divname, stockname):
    stockname = _attach_division(stockname, divname)
    rp = (retail_price
          .rename(columns={"ware_id": "product_id"})
          .merge(divname[["id", "division"]].rename(columns={"id": "division_id"}),
                 on="division_id", how="left"))
    rp = rp.drop_duplicates(["product_id", "division"], keep="last")
 
    # Note: original code groups by (product_id, division) — name, not id — preserving that.
    wh = stockname[["warehouse_id", "division", "name"]].rename(columns={"name": "warehouse_name"})
    merged = stock.merge(wh, on="warehouse_id", how="left")
    wn = merged["warehouse_name"].str.lower()
    merged = merged.loc[~(wn.eq("stock j&w") | wn.str.contains("выставка", na=False))]
    qty = merged.groupby(["product_id", "division"], as_index=False).agg(quantity=("quantity", "sum"))
    rp = rp.merge(qty, on=["product_id", "division"], how="left")
 
    rp = rp.merge(
        products[["product_id", "bu", "brand", "article", "individual_number",
                  "category", "group", "product", "consigment", "name"]],
        on="product_id", how="left",
    )
 
    # ── Apply article-transition mapping (two-stage) ────────────────────────
    repeated = cartier_transition.loc[cartier_transition["repeated"] == "yes", ["old", "new"]]
    final    = cartier_transition.loc[cartier_transition["repeated"] == "no",  ["old", "new"]]
 
    rp = rp.merge(repeated, left_on="article", right_on="old", how="left")
    rp["new"] = rp["new"].fillna(rp["article"])
    rp = rp.rename(columns={"article": "dwh_article", "new": "temporary_article"}).drop(columns="old")
 
    rp = rp.merge(final, left_on="temporary_article", right_on="old", how="left")
    rp["new"] = rp["new"].fillna(rp["temporary_article"])
    rp = rp.drop(columns=["old", "temporary_article"]).rename(columns={"new": "article"})
 
    rp = rp.loc[
        (rp["quantity"] > 0)
        & rp["category"].isin(["Jewelry", "Watches"])
        & (rp["consigment"] == False)
        & (rp["bu"] == "J&W")
        & rp["brand"].isin(["Van Cleef & Arpels", "Cartier"])
        & rp["article"].notna()
    ].copy()
 
    # Exclude Van Cleef & Arpels products listed in the VCA exclusion file.
    # These product_ids are removed from ALL downstream processes (transition
    # mapping, trimming, pairing, output) — not just filtered from the final
    # paired result. Normalize product_id (strip + remove spaces) to match the
    # format used everywhere else in the pipeline.
    vca_exclude = pd.read_excel(VCA_EXCLUDE_FILE, index_col=False)
    vca_exclude_ids = (vca_exclude["код спрута"]
                       .astype(str).str.strip().str.replace(" ", "", regex=False))
    rp = rp.loc[~(
        (rp["brand"] == "Van Cleef & Arpels")
        & rp["product_id"].isin(vca_exclude_ids)
    )].copy()
    
    # Trim rules differ by brand:
    #  - Cartier: trim ONLY when product is ring-like (contains 'ring',
    #    case-insensitive) or exactly 'Bracelet'. All other Cartier products
    #    are left untouched.
    #  - Van Cleef & Arpels: keep the original rule — trim EXCEPT earrings,
    #    watches, necklaces.
    # In both cases only trim when the article is long enough (>2 chars) so we
    # never blank a short article.
    is_cartier = rp["brand"] == "Cartier"
    long_enough = rp["article"].astype(str).str.len() > 2
 
    cartier_mask = (
        is_cartier
        & long_enough
        & (rp["product"] != "Earrings")
        & (
            rp["product"].fillna("").str.lower().str.contains("ring")
            | (rp["product"] == "Bracelet")
        )
    )
 
    vca_mask = (
        ~is_cartier
        & long_enough
        & (rp["product"] != "Earrings")
        & (rp["category"] != "Watches")
        & (rp["product"] != "Necklace")
    )
 
    mask = cartier_mask | vca_mask
    rp.loc[mask, "article"] = rp.loc[mask, "article"].astype(str).str[:-2]
 
    # dwh_article (original DB article, set pre-mapping above) is carried through
    # the self-merge by _build_pairs_within_article for both sides automatically.
    paired = _build_pairs_within_article(rp, products, purchases, group_key="article")
    if paired.empty:
        return paired
 
    # Cartier reference prices.
    # IMPORTANT: select ONLY the columns we need before merging. The source
    # sheet may contain other columns (e.g. its own 'article') that would
    # collide with paired's columns and get auto-suffixed (article_x/article_y),
    # which silently drops our real 'article' ("Артикул") from the output.
    cartier_prices = pd.read_excel(CARTIER_PRICES_FILE, index_col=False)
    cartier_prices = cartier_prices[["full_article", "price_cartier"]]
    paired = (paired
              .merge(cartier_prices, on="full_article", how="left")
              .merge(cartier_prices.rename(columns={
                        "full_article":  "full_article_last",
                        "price_cartier": "price_cartier_last"}),
                     on="full_article_last", how="left"))
 
    # If both sides match Cartier reference (different ref prices though), drop
    paired = paired.loc[~(
        (paired["price_cartier"] != paired["price_cartier_last"])
        & (paired["price_cartier"] == paired["full_retail_price"])
        & (paired["price_cartier_last"] == paired["full_retail_price_last"])
    )]
 
    cartier_exclude = pd.read_excel(CARTIER_EXCLUDE_FILE, index_col=False)
    paired = paired.loc[~paired["full_article"].isin(cartier_exclude["full_article"])]
 
    return paired
 
 
# ─────────────────── EXCEL OUTPUT PER MANAGER ───────────────────────────────
@task
def creating_files(df, df_vca_cartier, df_chopard):
    df_res = pd.concat([df, df_vca_cartier, df_chopard], sort=False)
    if "Группа" not in df_res.columns:
        df_res["Группа"] = ""
    else:
        df_res["Группа"] = df_res["Группа"].fillna("")
    # For non-Chopard brands (and Chopard PATH B) there is no reference Группа;
    # fall back to the product's own group so the column isn't blank everywhere.
    if "group" in df_res.columns:
        empty_grp = df_res["Группа"].isin(["", None]) | df_res["Группа"].isnull()
        df_res.loc[empty_grp, "Группа"] = df_res.loc[empty_grp, "group"].fillna("")
    df_res = df_res.loc[~df_res["brand"].isin(["Zen Diamonds"])].reset_index(drop=True)
    df_res.loc[df_res["full_article_last"].isnull(), "full_article_last"] = df_res["full_article"]
    # Mirror the same safety back-fill for the 1C article so "Артикул 1C \"2\""
    # is never blank when the right side didn't carry a value.
    if "dwh_article_last" not in df_res.columns:
        df_res["dwh_article_last"] = df_res.get("dwh_article", "")
    df_res.loc[df_res["dwh_article_last"].isnull(), "dwh_article_last"] = df_res["dwh_article"]
 
    rounding_cols = [f"last_buying_price_{ccy}{suf}"
                     for ccy in ("kzt", "eur", "usd", "chf")
                     for suf in ("", "_last")]
    df_res[rounding_cols] = df_res[rounding_cols].round()
 
    brand_manager = pd.read_excel(BRAND_MANAGER_FILE, index_col=False)
    df_res = df_res.merge(brand_manager, on="brand", how="left")
 
    keep = ["manager", "price_date", "price_date_last", "brand",
            "product_id", "product_id_last", "product", "product_last",
            "article", "Группа",
            "dwh_article", "dwh_article_last",
            "full_article", "full_article_last",
            "name", "name_last",
            "individual_number", "individual_number_last",
            "full_retail_price", "division",
            "full_retail_price_last", "division_last",
            "consigment", "consigment_last",
            "last_buying_price_kzt", "last_buying_price_kzt_last",
            "last_buying_price_eur", "last_buying_price_eur_last",
            "last_buying_price_usd", "last_buying_price_usd_last",
            "last_buying_price_chf", "last_buying_price_chf_last",
            "price_cartier", "price_cartier_last",
            "max_price_in_group"]
    # Some columns (price_cartier, dwh_article) only exist for VCA/Cartier branch.
    for col in keep:
        if col not in df_res.columns:
            df_res[col] = ""
 
    rename_map = {
        "manager": "Менеджер",
        "price_date": 'Дата установки цены 1',
        "price_date_last": 'Дата установки цены 2',
        "brand": "Бренд",
        "product_id": 'Код спрута "1"',
        "product_id_last": 'Код спрута "2"',
        "product": "Вид изделия",
        "product_last": "Вид изделия 2",
        "article": "Модель",
        "Группа": "Группа",
        "dwh_article": 'Артикул 1C "1"',
        "dwh_article_last": 'Артикул 1C "2"',
        "full_article": 'Артикул Актуальный "1"',
        "full_article_last": 'Артикул Актуальный "2"',
        "name": 'Наименование товара "1"',
        "name_last": 'Наименование товара "2"',
        "individual_number": 'Инд. Номер "1"',
        "individual_number_last": 'Инд. Номер "2"',
        "full_retail_price": 'Цена продажи с НДС, KZT "1"',
        "division": 'Магазин заведения цены "1"',
        "full_retail_price_last": 'Цена продажи с НДС, KZT "2"',
        "division_last": 'Магазин заведения цены "2"',
        "consigment": 'Консигнация "1"',
        "consigment_last": 'Консигнация "2"',
        "last_buying_price_kzt": 'Цена закупки, KZT "1"',
        "last_buying_price_kzt_last": 'Цена закупки, KZT "2"',
        "last_buying_price_eur": 'Цена закупки, EUR "1"',
        "last_buying_price_eur_last": 'Цена закупки, EUR "2"',
        "last_buying_price_usd": 'Цена закупки, USD "1"',
        "last_buying_price_usd_last": 'Цена закупки, USD "2"',
        "last_buying_price_chf": 'Цена закупки, CHF "1"',
        "last_buying_price_chf_last": 'Цена закупки, CHF "2"',
        "price_cartier": 'Цена Cartier, KZT "1"',
        "price_cartier_last": 'Цена Cartier, KZT "2"',
        "max_price_in_group": 'Максимальная цена по Модели "1"',
    }
    df_res = df_res[keep].rename(columns=rename_map)
 
    # Derived columns. Computed AFTER rename so we work with the final
    # display-named columns. Order of assignment defines column order in the
    # Excel output (pandas appends new columns at the right).
    max1   = pd.to_numeric(df_res['Максимальная цена по Модели "1"'], errors="coerce")
    price1 = pd.to_numeric(df_res['Цена продажи с НДС, KZT "1"'],     errors="coerce")
    price2 = pd.to_numeric(df_res['Цена продажи с НДС, KZT "2"'],     errors="coerce")
 
    df_res['Максимальная цена по Модели "2"'] = max1
    df_res['Разница по Модели "1", тнг.']     = max1 - price1
    df_res['Разница по Модели "2", тнг.']     = max1 - price2
    # Percentage as decimal ratio so Excel can format the cell as %.
    df_res['Разница по Модели "1", %']        = price1 / max1
    df_res['Разница по Модели "2", %']        = price2 / max1
    # Корректная цена placeholders (moved here per the spec).
    df_res['Корректная цена, KZT "1"']        = ""
    df_res['Корректная цена, KZT "2"']        = ""
    # Duplicate the product IDs at the end (no quotes, per the spec — distinct
    # column names from the existing 'Код спрута "1"'/'"2"' near the start).
    df_res['Код спрута 1'] = df_res['Код спрута "1"']
    df_res['Код спрута 2'] = df_res['Код спрута "2"']
 
    results_files = []
    for man in brand_manager["manager"].dropna().unique():
        loc = df_res.loc[df_res["Менеджер"] == man]
        path = FILE_PATH + str(man) + ".xlsx"
        save_excel(loc, path)
        results_files.append(path)
 
    no_man_path = FILE_PATH + "no_manager.xlsx"
    save_excel(df_res.loc[df_res["Менеджер"].isnull()], no_man_path)
    results_files.append(no_man_path)
 
    return results_files


# ─────────────────── PREFECT FLOW ───────────────────────────────────────────
_PURCHASES_SQL = """
WITH RankedRows AS (
    SELECT
        product_id, purchase_date,
        amount_kzt, amount_eur, amount_usd, amount_chf, quantity,
        ROW_NUMBER() OVER (PARTITION BY product_id ORDER BY purchase_date DESC) AS row_num
    FROM [DWH].[Fact].[v_Purchases]
    WHERE recorder_type = 'Поступление товаров и услуг'
)
SELECT product_id, purchase_date,
       amount_kzt, amount_eur, amount_usd, amount_chf, quantity
FROM RankedRows
WHERE row_num = 1;
"""


@flow
def price_corr(recipients: str):
    # ONE connection for every dimension/fact read.
    with get_conn() as conn:
        products     = get_sql_table(table_name="Dimension.v_product_v2", conn=conn)
        stock        = get_sql_table(table_name="Fact.stock",            conn=conn)
        divname      = get_sql_table(table_name="Dimension.Division",    conn=conn)
        stockname    = get_sql_table(table_name="Dimension.Warehouse",   conn=conn)
        retail_price = get_sql_table(table_name="Dimension.RetailPrice", conn=conn)
        purchases    = pd.read_sql_query(_PURCHASES_SQL, conn)

    products  = products_corrections(products)
    stock     = stock_corrections(stock, products)
    purchases = purchases_corrections(purchases)

    res                = p_cor(products, stock, retail_price, purchases, divname, stockname)
    res_vca_cartier    = p_cor_vca_cartier(products, stock, retail_price, purchases, divname, stockname)
    res_chopard        = p_cor_chopard(products, stock, retail_price, purchases, divname, stockname)
    result_files       = creating_files(res, res_vca_cartier, res_chopard)

    # SMTP credentials from Prefect Secrets — never hard-coded.

    body = (
        "Добрый день,\n\n"
        "Во вложении файлы с данными для выравнивания цен.\n\n"
        "Процедура проверки и выравнивания цен осуществляется непрерывно "
        "в первый рабочий день каждой недели.\n\n"
        "Обратную связь необходимо предоставить в ДАиОД Бойченко Павлу (p.boychenko@viled.kz).\n\n"
        "Срок на обработку данных: 2 рабочих дня. (например, если файл был "
        "получен в пн, то до среды 11-00).\n\n"
        "Бренд-менеджеры несут ответственность за несвоевременное "
        "предоставление данных."
    )

    for recipient in [r.strip() for r in recipients.split(";") if r.strip()]:
        email_send_message(
            email_server_credentials=creds,
            email_from='viledmailkz@gmail.com',
            subject="Viled J&W Price Correction file",
            msg=body,
            email_to=recipient,
            msg_plain=None,
            email_to_cc=None,
            email_to_bcc=None,
            attachments=result_files,
        )
