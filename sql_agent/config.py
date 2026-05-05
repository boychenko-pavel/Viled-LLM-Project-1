from __future__ import annotations

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = Path(r"C:\Users\p.boychenko\secrets\SQL_Password.env")
MEMORY_DIR = PROJECT_ROOT / ".agent_memory"
MEMORY_FILE = MEMORY_DIR / "sql_agent_memory.json"
REQUIRED_KEYS = ("DB_USER", "DB_PASSWORD", "DB_HOST", "DB_NAME")
LM_STUDIO_BASE_URL = "http://127.0.0.1:1234/v1"
LM_STUDIO_MODEL = "llama-3.2-3b-instruct"
MAX_HISTORY_MESSAGES = 12
MAX_SCHEMA_CHARS = 18000
MAX_HISTORY_CHARS = 1200
MAX_INSTRUCTIONS_CHARS = 1200
MAX_PROMPT_SCHEMA_CHARS = 1200
DEFAULT_PREVIEW_ROWS = 10
CURRENCY_ALIAS_MAP = {
    "usd": "full_retail_price_usd",
    "dol": "full_retail_price_usd",
    "dollar": "full_retail_price_usd",
    "dollars": "full_retail_price_usd",
    "\u0434\u043e\u043b": "full_retail_price_usd",
    "\u0434\u043e\u043b\u043b\u0430\u0440": "full_retail_price_usd",
    "\u0434\u043e\u043b\u043b\u0430\u0440\u044b": "full_retail_price_usd",
    "kzt": "full_retail_price_kzt",
    "nyu": "full_retail_price_kzt",
    "tenge": "full_retail_price_kzt",
    "\u0442\u0435\u043d\u0433\u0435": "full_retail_price_kzt",
    "eur": "full_retail_price_eur",
    "euro": "full_retail_price_eur",
    "\u0435\u0432\u0440\u043e": "full_retail_price_eur",
}
