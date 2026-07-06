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
