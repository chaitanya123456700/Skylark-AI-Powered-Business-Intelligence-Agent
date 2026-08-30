import os
import json
from dotenv import load_dotenv

load_dotenv()

MONDAY_API_TOKEN = os.environ.get("MONDAY_API_TOKEN")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.6-flash")

_DEFAULT_MAPPING_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "column_mapping.json")
MAPPING_PATH = os.environ.get("COLUMN_MAPPING_PATH", _DEFAULT_MAPPING_PATH)


def load_mapping() -> dict:
    if not os.path.exists(MAPPING_PATH):
        raise FileNotFoundError(
            f"column_mapping.json not found at {MAPPING_PATH}. "
            "Copy column_mapping.example.json to column_mapping.json, then run "
            "'python discover_columns.py <board_id>' for each board and fill in the real "
            "column IDs and board_ids."
        )
    with open(MAPPING_PATH, "r") as f:
        return json.load(f)


def require_tokens():
    missing = []
    if not MONDAY_API_TOKEN:
        missing.append("MONDAY_API_TOKEN")
    if not GEMINI_API_KEY :
        missing.append("ANTHROPIC_API_KEY")
    if missing:
        raise RuntimeError(
            f"Missing required environment variable(s): {', '.join(missing)}. "
            "Copy .env.example to .env and fill them in."
        )
