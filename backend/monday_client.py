"""
Thin wrapper around the monday.com GraphQL API (v2).
Read-only: this app never writes back to monday.com.
"""
import requests
from config import MONDAY_API_TOKEN

MONDAY_API_URL = "https://api.monday.com/v2"
API_VERSION = "2024-10"


def _run_query(query: str, variables: dict | None = None) -> dict:
    if not MONDAY_API_TOKEN:
        raise RuntimeError("MONDAY_API_TOKEN is not set. Copy .env.example to .env and fill it in.")
    headers = {
        "Authorization": MONDAY_API_TOKEN,
        "Content-Type": "application/json",
        "API-Version": API_VERSION,
    }
    resp = requests.post(
        MONDAY_API_URL,
        json={"query": query, "variables": variables or {}},
        headers=headers,
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    if "errors" in data:
        raise RuntimeError(f"monday.com API error: {data['errors']}")
    return data["data"]


def list_board_columns(board_id: int) -> list[dict]:
    """Used by discover_columns.py to help map logical fields -> real column IDs."""
    query = """
    query ($boardId: [ID!]) {
      boards(ids: $boardId) {
        name
        columns {
          id
          title
          type
        }
      }
    }
    """
    data = _run_query(query, {"boardId": [str(board_id)]})
    boards = data.get("boards") or []
    if not boards:
        raise RuntimeError(f"Board {board_id} not found or not accessible with this API token.")
    return boards[0]["columns"]


def get_board_items(board_id: int) -> list[dict]:
    """
    Returns every item on a board as a flat dict: {"id", "name", <column_id>: <text value>, ...}.
    Paginates via items_page until the cursor is exhausted.
    """
    query = """
    query ($boardId: [ID!], $cursor: String) {
      boards(ids: $boardId) {
        items_page(limit: 100, cursor: $cursor) {
          cursor
          items {
            id
            name
            column_values {
              id
              text
              value
            }
          }
        }
      }
    }
    """
    items: list[dict] = []
    cursor = None
    while True:
        data = _run_query(query, {"boardId": [str(board_id)], "cursor": cursor})
        boards = data.get("boards") or []
        if not boards:
            raise RuntimeError(f"Board {board_id} not found or not accessible with this API token.")
        page = boards[0]["items_page"]
        for item in page["items"]:
            row = {"id": item["id"], "name": item["name"]}
            for cv in item["column_values"]:
                # `text` is the human-readable rendering monday.com computes for each column type;
                # good enough for status/text/date/number columns without per-type parsing.
                row[cv["id"]] = cv["text"]
            items.append(row)
        cursor = page.get("cursor")
        if not cursor:
            break
    return items
