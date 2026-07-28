from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = Path(r"C:\Users\p.boychenko\secrets\SQL_Password.env")
OPENAI_SECRETS_FILE = Path.home() / "secrets" / "OpenAI_API_KEY.env"
load_dotenv(OPENAI_SECRETS_FILE)
MEMORY_DIR = PROJECT_ROOT / ".agent_memory"
MEMORY_FILE = MEMORY_DIR / "sql_agent_memory.json"
REQUIRED_KEYS = ("DB_USER", "DB_PASSWORD", "DB_HOST", "DB_NAME")
LM_STUDIO_BASE_URL = "http://127.0.0.1:1234/v1"
LM_STUDIO_MODEL = "llama-3.2-3b-instruct"
LM_STUDIO_EMBEDDING_MODEL = "text-embedding-nomic-embed-text-v1.5@f32"
LM_STUDIO_MANAGE_MODELS_DURING_EMBEDDING = True
HR_TESSERACT_CMD = Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe")
HR_OCR_LANGUAGES = "rus+eng"
MAX_HISTORY_MESSAGES = 12
MAX_SCHEMA_CHARS = 18000
MAX_HISTORY_CHARS = 1200
MAX_INSTRUCTIONS_CHARS = 1200
MAX_PROMPT_SCHEMA_CHARS = 1200
DEFAULT_PREVIEW_ROWS = 100
OPENAI_SQL_REVIEW_ENABLED = os.getenv("OPENAI_SQL_REVIEW_ENABLED", "1").strip().lower() not in {
    "0",
    "false",
    "no",
    "off",
}
OPENAI_SQL_REVIEW_MODEL = os.getenv("OPENAI_SQL_REVIEW_MODEL", "gpt-5.6").strip()
OPENAI_SQL_REVIEW_TIMEOUT_SECONDS = float(
    os.getenv("OPENAI_SQL_REVIEW_TIMEOUT_SECONDS", "30")
)
CURRENCY_ALIAS_MAP = {
    "usd": "full_retail_price_usd",
    "dol": "full_retail_price_usd",
    "dollar": "full_retail_price_usd",
    "dollars": "full_retail_price_usd",
    "дол": "full_retail_price_usd",
    "доллар": "full_retail_price_usd",
    "доллары": "full_retail_price_usd",
    "kzt": "full_retail_price_kzt",
    "nyu": "full_retail_price_kzt",
    "tenge": "full_retail_price_kzt",
    "тенге": "full_retail_price_kzt",
    "eur": "full_retail_price_eur",
    "euro": "full_retail_price_eur",
    "евро": "full_retail_price_eur",
}
