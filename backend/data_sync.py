"""
The only place this app talks to monday.com for row data. Everything downstream
(metrics, SQL fallback, notes search) reads from the in-memory cache / DuckDB
tables built here - never from the original CSVs.
"""
import time
import datetime
import duckdb
import pandas as pd

from monday_client import get_board_items
from normalize import normalize_date, normalize_number, normalize_text, clean_null
from config import load_mapping

TTL_SECONDS = 300  # re-pull from monday.com at most every 5 minutes unless force_refresh

STAGE_SYNONYMS = {
    "closed won": "Won", "won": "Won", "win": "Won",
    "closed lost": "Lost", "lost": "Lost", "lose": "Lost",
    "proposal sent": "Proposal", "proposal": "Proposal",
    "negotiating": "Negotiation", "negotiation": "Negotiation",
    "prospecting": "Prospecting", "prospect": "Prospecting", "new": "Prospecting",
}
STATUS_SYNONYMS = {
    "complete": "Completed", "completed": "Completed", "done": "Completed",
    "in progress": "In Progress", "ongoing": "In Progress", "wip": "In Progress",
    "not started": "Not Started", "not yet started": "Not Started",
    "on hold": "On Hold", "paused": "On Hold", "hold": "On Hold",
}

_cache = {"deals": None, "work_orders": None, "synced_at": 0, "dq": {}}
_conn = duckdb.connect(database=":memory:")


def _map_row(raw_row: dict, mapping: dict) -> dict:
    out = {"id": raw_row.get("id"), "name": raw_row.get("name")}
    for logical_field, column_id in mapping.items():
        out[logical_field] = raw_row.get(column_id)
    return out


def _build_deals_df(raw_items, mapping) -> pd.DataFrame:
    rows = [_map_row(r, mapping) for r in raw_items]
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    for col in ("client", "owner"):
        if col in df:
            df[col] = df[col].apply(lambda v: normalize_text(v))
    if "sector" in df:
        df["sector"] = df["sector"].apply(lambda v: normalize_text(v))
    if "stage" in df:
        df["stage"] = df["stage"].apply(lambda v: normalize_text(v, STAGE_SYNONYMS))
    for col in ("value", "probability"):
        if col in df:
            df[col] = df[col].apply(normalize_number)
            if col == "probability":
                # accept either "0.4" or "40" style probability entries -> store as 0-1
                df[col] = df[col].apply(lambda v: v / 100 if v is not None and v > 1 else v)
    for col in ("expected_close_date", "actual_close_date"):
        if col in df:
            df[col] = df[col].apply(normalize_date)
    if "notes" in df:
        df["notes"] = df["notes"].apply(clean_null)
    return df


def _build_work_orders_df(raw_items, mapping) -> pd.DataFrame:
    rows = [_map_row(r, mapping) for r in raw_items]
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    for col in ("client", "owner", "project_name"):
        if col in df:
            df[col] = df[col].apply(lambda v: normalize_text(v))
    if "sector" in df:
        df["sector"] = df["sector"].apply(lambda v: normalize_text(v))
    if "status" in df:
        df["status"] = df["status"].apply(lambda v: normalize_text(v, STATUS_SYNONYMS))
    for col in ("budget", "revenue_recognized"):
        if col in df:
            df[col] = df[col].apply(normalize_number)
    for col in ("start_date", "planned_end_date", "actual_end_date"):
        if col in df:
            df[col] = df[col].apply(normalize_date)
    if "notes" in df:
        df["notes"] = df["notes"].apply(clean_null)
    return df


def _dq_report(df: pd.DataFrame, name: str) -> dict:
    if df is None or df.empty:
        return {"table": name, "row_count": 0, "missing_pct": {}}
    missing = (df.isna().mean() * 100).round(1).to_dict()
    return {"table": name, "row_count": int(len(df)), "missing_pct": missing, "as_of": datetime.datetime.utcnow().isoformat()}


def sync_and_normalize(force_refresh: bool = False):
    now = time.time()
    if not force_refresh and _cache["deals"] is not None and (now - _cache["synced_at"] < TTL_SECONDS):
        return _cache["deals"], _cache["work_orders"]

    mapping = load_mapping()
    deals_board_id = mapping["board_ids"]["deals"]
    wo_board_id = mapping["board_ids"]["work_orders"]

    deals_raw = get_board_items(deals_board_id)
    wo_raw = get_board_items(wo_board_id)

    deals_df = _build_deals_df(deals_raw, mapping["deals"])
    wo_df = _build_work_orders_df(wo_raw, mapping["work_orders"])

    _conn.execute("DROP TABLE IF EXISTS deals")
    _conn.execute("DROP TABLE IF EXISTS work_orders")
    _conn.register("deals_view", deals_df)
    _conn.register("wo_view", wo_df)
    _conn.execute("CREATE TABLE deals AS SELECT * FROM deals_view")
    _conn.execute("CREATE TABLE work_orders AS SELECT * FROM wo_view")

    _cache["deals"] = deals_df
    _cache["work_orders"] = wo_df
    _cache["synced_at"] = now
    _cache["dq"] = {
        "deals": _dq_report(deals_df, "deals"),
        "work_orders": _dq_report(wo_df, "work_orders"),
    }
    return deals_df, wo_df


def get_dataframes():
    if _cache["deals"] is None:
        sync_and_normalize()
    return _cache["deals"], _cache["work_orders"]


def get_data_quality_report() -> dict:
    if not _cache["dq"]:
        sync_and_normalize()
    return _cache["dq"]


def get_duckdb_conn():
    get_dataframes()
    return _conn
