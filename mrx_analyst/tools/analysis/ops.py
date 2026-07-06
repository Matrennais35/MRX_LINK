"""The tested analysis operations — pure pandas, golden-tested.

These are the deterministic computations the Analyst prefers over free-form
codegen: attribution (who drove a net move), two-period variance, and
concentration. Each is a plain function over a DataFrame so it's trivially
golden-testable; the Tool adapters in toolkit.py resolve evidence labels and
wrap these for agent-proposed calls.
"""

from typing import List, Optional

import pandas as pd


def _leafify(df: pd.DataFrame) -> pd.DataFrame:
    """MRX Depth hierarchies carry ancestor rows that DUPLICATE child sums —
    grouping over them double-counts (a real eval failure). When a Depth
    column is present, keep leaf rows only (a row is an ancestor when the
    next row is deeper). Flat frames pass through untouched."""
    if "Depth" not in df.columns or df["Depth"].nunique() <= 1:
        return df
    has_child = df["Depth"].shift(-1).fillna(df["Depth"]) > df["Depth"]
    return df[~has_child]


def attribution(df: pd.DataFrame, group_cols: List[str], value_col: str,
                top_n: int = 10) -> pd.DataFrame:
    """Signed contribution of each group to the net total of `value_col`.

    Returns columns: group_cols..., contribution, share_of_net (signed share of
    the NET move — the analyst convention: an offset has a negative share),
    sorted by |contribution| descending, top_n rows. This is the computation
    behind every "what drove X" answer.
    """
    df = _leafify(df)
    grouped = df.groupby(group_cols, dropna=False)[value_col].sum().reset_index()
    grouped = grouped.rename(columns={value_col: "contribution"})
    net = grouped["contribution"].sum()
    grouped["share_of_net"] = grouped["contribution"] / net if net != 0 else float("nan")
    grouped = grouped.reindex(
        grouped["contribution"].abs().sort_values(ascending=False).index
    )
    return grouped.head(top_n).reset_index(drop=True)


def variance(df: pd.DataFrame, group_cols: List[str], current_col: str,
             previous_col: str, top_n: int = 10) -> pd.DataFrame:
    """Two-period delta by group (the MRX Current/Previous frame shape).

    Returns: group_cols..., current, previous, delta, pct_change — sorted by
    |delta| descending, top_n rows. pct_change is NaN where previous == 0
    (an honest gap beats an infinite percentage).
    """
    df = _leafify(df)
    grouped = df.groupby(group_cols, dropna=False)[[current_col, previous_col]].sum().reset_index()
    grouped = grouped.rename(columns={current_col: "current", previous_col: "previous"})
    grouped["delta"] = grouped["current"] - grouped["previous"]
    prev = grouped["previous"]
    grouped["pct_change"] = grouped["delta"].where(prev != 0) / prev.where(prev != 0)
    grouped = grouped.reindex(grouped["delta"].abs().sort_values(ascending=False).index)
    return grouped.head(top_n).reset_index(drop=True)


def concentration(df: pd.DataFrame, group_col: str, value_col: str) -> dict:
    """How concentrated |value| is across `group_col`: HHI, top-1/top-5 share,
    and the ranked share table. The 'is this one big position or many small
    ones' question behind concentration-vs-offsetting narratives."""
    df = _leafify(df)
    shares = (
        df.groupby(group_col, dropna=False)[value_col]
        .apply(lambda s: float(s.abs().sum()))
        .sort_values(ascending=False)
    )
    total = float(shares.sum())
    if total == 0:
        return {"hhi": 0.0, "top1_share": 0.0, "top5_share": 0.0,
                "table": shares.reset_index(name="abs_value")}
    normalized = shares / total
    table = shares.reset_index(name="abs_value")
    table["share"] = normalized.values
    return {
        "hhi": float((normalized ** 2).sum()),
        "top1_share": float(normalized.iloc[0]),
        "top5_share": float(normalized.head(5).sum()),
        "table": table,
    }


def trend(df: pd.DataFrame, top_jumps: int = 3) -> dict:
    """Characterize a daily series from a wide MRX History-dates frame: the
    dated moves, not just the endpoint difference (the eval's Q1 said "no jump
    attribution available" while holding exactly this data).

    Sums leaf rows per date column, then returns:
    - "table": the JUMPS table — the top_jumps largest daily moves WITH DATES
      (Date, Value, Change) plus first/last rows for anchoring.
    - "tables": {"trend_series": long DataFrame [Date, Value] ascending} —
      registered as evidence, chartable via evolution_chart.
    - scalars: start, end, net, pct_change, largest_jump_date.
    """
    import re as _re
    date_re = _re.compile(r"^\d{4}[-/]\d{2}[-/]\d{2}$")
    date_cols = sorted(str(c) for c in df.columns if date_re.match(str(c)))
    if len(date_cols) < 2:
        raise ValueError("trend needs a wide frame with at least 2 date-named columns "
                         f"— found {len(date_cols)}")
    body = _leafify(df)
    values = [float(pd.to_numeric(body[c], errors="coerce").sum()) for c in date_cols]
    series = pd.DataFrame({"Date": date_cols, "Value": values})
    series["Change"] = series["Value"].diff()

    start, end = values[0], values[-1]
    net = end - start
    changes = series.dropna(subset=["Change"])
    ranked = changes.reindex(changes["Change"].abs().sort_values(ascending=False).index)
    jump_rows = ranked.head(top_jumps)
    anchors = series.iloc[[0, -1]]
    jumps = (pd.concat([anchors, jump_rows])
             .drop_duplicates(subset=["Date"]).sort_values("Date").reset_index(drop=True))

    return {
        "table": jumps,
        "tables": {"trend_series": series[["Date", "Value"]]},
        "start": start,
        "end": end,
        "net": net,
        "pct_change": (net / abs(start)) if start else float("nan"),
        "largest_jump_date": str(ranked.iloc[0]["Date"]) if len(ranked) else "",
    }


def position_change(df: pd.DataFrame, label_cols: List[str], current_col: str,
                    previous_col: str, top_n: int = 5) -> dict:
    """Decompose a change into WHAT KIND of change it was — the 'why' MRX can
    answer deterministically (the eval's USDHKD build was mostly NEW positions,
    visible in the data and never stated):

    - NEW: previous == 0, current != 0 (positions that didn't exist before)
    - CLOSED: current == 0, previous != 0
    - EXISTING: both non-zero (revaluation / resize of standing positions)

    Returns "table": one row per bucket (count, current, previous, delta,
    share_of_net); "tables": {"position_detail": top_n contributors per bucket
    by |delta|}; scalars: net + per-bucket deltas. Leaf-only under Depth.
    """
    body = _leafify(df)
    grouped = body.groupby(label_cols, dropna=False)[[current_col, previous_col]].sum().reset_index()
    grouped = grouped.rename(columns={current_col: "current", previous_col: "previous"})
    grouped["delta"] = grouped["current"] - grouped["previous"]

    def _bucket(row):
        if row["previous"] == 0 and row["current"] != 0:
            return "new"
        if row["current"] == 0 and row["previous"] != 0:
            return "closed"
        return "existing"

    grouped["bucket"] = grouped.apply(_bucket, axis=1)
    net = float(grouped["delta"].sum())

    summary = (grouped.groupby("bucket")
               .agg(positions=("delta", "size"), current=("current", "sum"),
                    previous=("previous", "sum"), delta=("delta", "sum"))
               .reindex(["new", "closed", "existing"]).dropna(how="all").reset_index())
    summary["share_of_net"] = summary["delta"] / net if net else float("nan")

    detail = (grouped.assign(_abs=grouped["delta"].abs())
              .sort_values(["bucket", "_abs"], ascending=[True, False])
              .groupby("bucket").head(top_n).drop(columns="_abs").reset_index(drop=True))

    scalars = {f"{b}_delta": float(summary.loc[summary["bucket"] == b, "delta"].sum())
               for b in summary["bucket"]}
    return {"table": summary, "tables": {"position_detail": detail},
            "net": net, **scalars}
