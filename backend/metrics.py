"""
Every function here is plain pandas - no LLM involved - so the common founder
questions never depend on freshly generated code. Each takes the relevant
DataFrame plus optional filter params and returns JSON-friendly native types.
"""
import datetime
import pandas as pd


def _filter_sector(df, sector):
    if sector and "sector" in df.columns:
        return df[df["sector"].str.lower() == str(sector).lower()]
    return df


def compute_pipeline_by_sector(deals_df, sector=None, include_closed=False):
    df = deals_df.copy()
    if not include_closed:
        df = df[~df["stage"].isin(["Won", "Lost"])]
    df = _filter_sector(df, sector)
    grouped = df.groupby("sector", dropna=False).agg(
        total_value=("value", "sum"), deal_count=("value", "count")
    ).reset_index()
    return {"by_sector": grouped.to_dict(orient="records"), "scope": "open pipeline" if not include_closed else "all deals"}


def compute_weighted_pipeline(deals_df, sector=None):
    df = deals_df.copy()
    df = df[~df["stage"].isin(["Won", "Lost"])]
    df = _filter_sector(df, sector)
    df = df.assign(weighted_value=df["value"].fillna(0) * df["probability"].fillna(0.5))
    by_sector = df.groupby("sector", dropna=False)["weighted_value"].sum().reset_index()
    return {
        "total_weighted_pipeline": round(float(df["weighted_value"].sum()), 2),
        "by_sector": by_sector.to_dict(orient="records"),
        "note": "Deals missing a probability were assumed at 50% for weighting.",
    }


def compute_win_rate(deals_df, sector=None, since_date=None):
    df = deals_df.copy()
    df = _filter_sector(df, sector)
    if since_date:
        df = df[df["actual_close_date"] >= since_date]
    closed = df[df["stage"].isin(["Won", "Lost"])]
    if len(closed) == 0:
        return {"win_rate": None, "won": 0, "lost": 0, "note": "No closed (Won/Lost) deals in scope."}
    won = int((closed["stage"] == "Won").sum())
    return {"win_rate": round(won / len(closed), 3), "won": won, "lost": int(len(closed) - won)}


def compute_avg_deal_cycle_time(deals_df, sector=None):
    df = deals_df.copy()
    df = df[df["stage"] == "Won"].dropna(subset=["expected_close_date", "actual_close_date"])
    df = _filter_sector(df, sector)
    if df.empty:
        return {"avg_cycle_days": None, "note": "Not enough data: need Won deals with both an expected and actual close date."}
    d1 = pd.to_datetime(df["expected_close_date"])
    d2 = pd.to_datetime(df["actual_close_date"])
    cycle = (d2 - d1).dt.days
    return {"avg_cycle_days": round(float(cycle.mean()), 1), "sample_size": int(len(df))}


def compute_wo_completion_rate(wo_df, sector=None):
    df = _filter_sector(wo_df.copy(), sector)
    if df.empty:
        return {"completion_rate": None, "note": "No work orders in scope."}
    completed = int((df["status"] == "Completed").sum())
    return {"completion_rate": round(completed / len(df), 3), "completed": completed, "total": int(len(df))}


def compute_on_time_delivery(wo_df, sector=None):
    df = wo_df.copy()
    df = df[df["status"] == "Completed"].dropna(subset=["planned_end_date", "actual_end_date"])
    df = _filter_sector(df, sector)
    if df.empty:
        return {"on_time_pct": None, "note": "No completed work orders with both a planned and actual end date."}
    on_time = int((pd.to_datetime(df["actual_end_date"]) <= pd.to_datetime(df["planned_end_date"])).sum())
    return {"on_time_pct": round(on_time / len(df), 3), "on_time": on_time, "total": int(len(df))}


def compute_overdue_work_orders(wo_df, as_of_date=None):
    as_of = pd.Timestamp(as_of_date) if as_of_date else pd.Timestamp(datetime.date.today())
    df = wo_df.copy()
    df = df[df["status"] != "Completed"].dropna(subset=["planned_end_date"])
    overdue = df[pd.to_datetime(df["planned_end_date"]) < as_of]
    cols = [c for c in ["id", "name", "client", "planned_end_date", "status"] if c in overdue.columns]
    return {"overdue_count": int(len(overdue)), "items": overdue[cols].to_dict(orient="records")}


def compute_revenue_vs_cost(wo_df, sector=None):
    df = _filter_sector(wo_df.copy(), sector)
    total_revenue = float(df["revenue_recognized"].sum()) if "revenue_recognized" in df else 0.0
    total_budget = float(df["budget"].sum()) if "budget" in df else 0.0
    return {
        "total_revenue_recognized": round(total_revenue, 2),
        "total_budget": round(total_budget, 2),
        "margin": round(total_revenue - total_budget, 2),
    }


def compute_stalled_deals(deals_df, sector=None, days=30):
    df = deals_df.copy()
    df = df[~df["stage"].isin(["Won", "Lost"])].dropna(subset=["expected_close_date"])
    df = _filter_sector(df, sector)
    today = pd.Timestamp(datetime.date.today())
    df = df.assign(days_past_expected=(today - pd.to_datetime(df["expected_close_date"])).dt.days)
    stalled = df[df["days_past_expected"] > days]
    cols = [c for c in ["id", "name", "client", "stage", "days_past_expected"] if c in stalled.columns]
    return {"stalled_count": int(len(stalled)), "threshold_days": days, "items": stalled[cols].to_dict(orient="records")}


KNOWN_METRICS = {
    "pipeline_by_sector": compute_pipeline_by_sector,
    "weighted_pipeline": compute_weighted_pipeline,
    "win_rate": compute_win_rate,
    "avg_deal_cycle_time": compute_avg_deal_cycle_time,
    "work_order_completion_rate": compute_wo_completion_rate,
    "on_time_delivery_pct": compute_on_time_delivery,
    "overdue_work_orders": compute_overdue_work_orders,
    "revenue_vs_cost": compute_revenue_vs_cost,
    "stalled_deals": compute_stalled_deals,
}

# which board's DataFrame each metric expects as its first argument
METRIC_TARGET = {
    "pipeline_by_sector": "deals",
    "weighted_pipeline": "deals",
    "win_rate": "deals",
    "avg_deal_cycle_time": "deals",
    "stalled_deals": "deals",
    "work_order_completion_rate": "work_orders",
    "on_time_delivery_pct": "work_orders",
    "overdue_work_orders": "work_orders",
    "revenue_vs_cost": "work_orders",
}
