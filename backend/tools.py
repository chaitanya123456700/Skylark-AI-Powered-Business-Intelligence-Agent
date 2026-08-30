from data_sync import get_dataframes, get_data_quality_report, get_duckdb_conn, sync_and_normalize
from metrics import KNOWN_METRICS, METRIC_TARGET
from notes_search import search_notes

TOOLS_SPEC = [
    {
        "name": "compute_metric",
        "description": (
            "Compute one of the pre-built, hand-verified business metrics. Always prefer this over "
            "run_sql_query when the question matches one of these metric names: "
            + ", ".join(KNOWN_METRICS.keys())
            + ". pipeline/weighted_pipeline/win_rate/avg_deal_cycle_time/stalled_deals read the Deals "
            "board. work_order_completion_rate/on_time_delivery_pct/overdue_work_orders/revenue_vs_cost "
            "read the Work Orders board."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "metric_name": {"type": "string", "enum": list(KNOWN_METRICS.keys())},
                "params": {
                    "type": "object",
                    "description": "Optional filters. Common ones: sector (string), days (int, for stalled_deals), since_date/as_of_date (YYYY-MM-DD).",
                },
            },
            "required": ["metric_name"],
        },
    },
    {
        "name": "run_sql_query",
        "description": (
            "Run a read-only DuckDB SELECT query for questions that don't match any pre-built metric "
            "(e.g. joining deals and work_orders, or an unusual filter/breakdown). Only a single SELECT "
            "statement is allowed - no writes.\n"
            "deals columns: id, name, client, sector, stage (Prospecting/Proposal/Negotiation/Won/Lost), "
            "value, probability (0-1), expected_close_date, actual_close_date, owner, notes.\n"
            "work_orders columns: id, name, client, sector, project_name, "
            "status (Not Started/In Progress/Completed/On Hold), start_date, planned_end_date, "
            "actual_end_date, owner, budget, revenue_recognized, notes."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"sql": {"type": "string", "description": "A single read-only SELECT statement."}},
            "required": ["sql"],
        },
    },
    {
        "name": "search_notes",
        "description": (
            "Keyword/fuzzy search over the free-text notes field on deals or work orders, for questions "
            "like 'which deals mentioned pricing concerns' or 'any work orders with client complaints'."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "board": {"type": "string", "enum": ["deals", "work_orders"]},
                "keyword": {"type": "string"},
            },
            "required": ["board", "keyword"],
        },
    },
    {
        "name": "get_data_quality_report",
        "description": (
            "Get row counts and missing-data percentages per column for both boards. Call this whenever "
            "you're about to state a number that depends on a field with meaningful missingness, so you "
            "can add an honest caveat."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "refresh_data",
        "description": "Force a fresh pull from monday.com, bypassing the cache. Only use if the user explicitly asks for the latest/live data.",
        "input_schema": {"type": "object", "properties": {}},
    },
]


def _is_safe_select(sql: str) -> bool:
    s = sql.strip().lower().rstrip(";")
    if ";" in s:
        return False  # no stacked statements
    if not s.startswith("select") and not s.startswith("with"):
        return False
    banned = ["insert", "update", "delete", "drop", "alter", "create", "attach", "copy", "pragma", "call"]
    return not any(f" {b} " in f" {s} " or s.startswith(b) for b in banned)


def execute_tool(name: str, tool_input: dict) -> dict:
    deals_df, wo_df = get_dataframes()

    if name == "compute_metric":
        metric_name = tool_input.get("metric_name")
        params = tool_input.get("params") or {}
        fn = KNOWN_METRICS.get(metric_name)
        if not fn:
            return {"error": f"Unknown metric '{metric_name}'."}
        target_df = deals_df if METRIC_TARGET[metric_name] == "deals" else wo_df
        try:
            return fn(target_df, **params)
        except TypeError as e:
            return {"error": f"Bad params for {metric_name}: {e}"}
        except Exception as e:
            return {"error": f"Failed computing {metric_name}: {e}"}

    if name == "run_sql_query":
        sql = tool_input.get("sql", "")
        if not _is_safe_select(sql):
            return {"error": "Only a single read-only SELECT/WITH statement is allowed."}
        try:
            conn = get_duckdb_conn()
            result_df = conn.execute(sql).df()
            return {"rows": result_df.head(200).to_dict(orient="records"), "row_count": int(len(result_df))}
        except Exception as e:
            return {"error": str(e)}

    if name == "search_notes":
        board = tool_input.get("board")
        keyword = tool_input.get("keyword", "")
        df = deals_df if board == "deals" else wo_df
        return {"matches": search_notes(df, keyword)}

    if name == "get_data_quality_report":
        return get_data_quality_report()

    if name == "refresh_data":
        sync_and_normalize(force_refresh=True)
        return {"status": "refreshed"}

    return {"error": f"Unknown tool '{name}'."}
