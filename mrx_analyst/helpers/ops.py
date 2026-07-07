"""The tested analysis operations — pure pandas, golden-tested.

These are the deterministic computations the Analyst prefers over free-form
codegen: attribution (who drove a net move), two-period variance, and
concentration. Each is a plain function over a DataFrame so it's trivially
golden-testable; the Tool adapters in toolkit.py resolve evidence labels and
wrap these for agent-proposed calls.
"""

from typing import List, Optional

import pandas as pd


def leafify(df: pd.DataFrame) -> pd.DataFrame:
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
    df = leafify(df)
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
    df = leafify(df)
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
    df = leafify(df)
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
    body = leafify(df)
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


_MATURITY_RE = None  # compiled lazily below


def _maturity_from_label(label: str):
    """MRX deal labels usually end with the option's maturity ('FXO STND Put
    2027-05-19') — parse it, so a CLOSED position can be classified as EXPIRED
    (maturity passed: the desk-note 'time decay / expiries' driver) vs UNWOUND
    (an active close). Returns the ISO date string or None."""
    global _MATURITY_RE
    import re as _re
    if _MATURITY_RE is None:
        _MATURITY_RE = _re.compile(r"(\d{4}-\d{2}-\d{2})")
    m = _MATURITY_RE.search(str(label))
    return m.group(1) if m else None


def position_change(df: pd.DataFrame, label_cols: List[str], current_col: str,
                    previous_col: str, top_n: int = 5,
                    as_of: str = "") -> dict:
    """Decompose a change into WHAT KIND of change it was — the categorized
    attribution a desk note leads with, derivable deterministically from MRX:

    - NEW: previous == 0, current != 0 (trading activity — positions added)
    - EXPIRED: current == 0 and the label's maturity date <= `as_of`
      (time decay / expiries — risk that rolled off)
    - UNWOUND: current == 0, no or future maturity (actively closed)
    - EXISTING: both non-zero (revaluation of standing positions — market
      moves / moneyness effects)

    `as_of` (ISO date) defaults to the current column's name when it is
    date-like. Returns "table": one row per bucket (count, current, previous,
    delta, share_of_net); "tables": {"position_detail": top_n contributors per
    bucket by |delta|}; scalars: net + per-bucket deltas. Leaf-only under Depth.
    """
    body = leafify(df)
    grouped = body.groupby(label_cols, dropna=False)[[current_col, previous_col]].sum().reset_index()
    grouped = grouped.rename(columns={current_col: "current", previous_col: "previous"})
    grouped["delta"] = grouped["current"] - grouped["previous"]

    if not as_of:
        candidate = str(current_col).replace("/", "-")
        as_of = candidate if _maturity_from_label(candidate) else ""

    def _bucket(row):
        if row["previous"] == 0 and row["current"] != 0:
            return "new"
        if row["current"] == 0 and row["previous"] != 0:
            if as_of:
                maturity = _maturity_from_label(row[label_cols[0]])
                if maturity and maturity <= as_of:
                    return "expired"
            return "unwound"
        return "existing"

    grouped["bucket"] = grouped.apply(_bucket, axis=1)
    net = float(grouped["delta"].sum())

    summary = (grouped.groupby("bucket")
               .agg(positions=("delta", "size"), current=("current", "sum"),
                    previous=("previous", "sum"), delta=("delta", "sum"))
               .reindex(["new", "expired", "unwound", "existing"])
               .dropna(how="all").reset_index())
    summary["share_of_net"] = summary["delta"] / net if net else float("nan")

    detail = (grouped.assign(_abs=grouped["delta"].abs())
              .sort_values(["bucket", "_abs"], ascending=[True, False])
              .groupby("bucket").head(top_n).drop(columns="_abs").reset_index(drop=True))

    scalars = {f"{b}_delta": float(summary.loc[summary["bucket"] == b, "delta"].sum())
               for b in summary["bucket"]}
    return {"table": summary, "tables": {"position_detail": detail},
            "net": net, **scalars}


def sweep_diagnostics(frames: dict, *, label_col: str = "Label",
                      current_col: str = "Total",
                      previous_col: str = "Total (prv)",
                      diff_col: str = "Total (diff)",
                      expected_net: Optional[float] = None,
                      rel_tol: float = 1e-3, top_n: int = 3) -> dict:
    """THE SWEEP DIAGNOSIS: given two-COB compare frames for SEVERAL candidate
    dimensions ({"product": df, "portfolio": df, ...}), rank the dimensions by
    how INFORMATIVE they are about the move.

    The decisive metric is DIVERGENCE = half the total variation distance
    between the move's distribution and the book's distribution across the
    dimension's labels. A book that is 60% product X moving 60% in product X
    is PROPORTIONAL (divergence ~0, not a story, whatever the top-1 share);
    the story lives where the move distributes DIFFERENTLY than the book.

    Returns (trend/position_change convention):
    - "table": one ranked row per dimension — divergence, net, gross,
      offset_ratio, top1_label, top1_share_gross, top1_share_net,
      top3_share_gross, hhi_move, n_rows, reconciled.
    - "tables": {"reconciliation": [dimension, net, deviation, ok]} — every
      dimension's leaf net vs the reference (expected_net or the median);
      a failing dimension is QUARANTINED (ok=False), never silently dropped.
    - scalars: "reference_net", "reconciled" (all ok), "top_dimension".
    """
    rows, nets = [], {}
    for dim, df in frames.items():
        try:
            leaves = leafify(df)
            leaves = leaves[leaves[label_col].astype(str).str.lower() != "total"]
            diff = (leaves[diff_col] if diff_col in leaves.columns
                    else leaves[current_col] - leaves[previous_col])
            prev = leaves[previous_col]
        except Exception:
            nets[dim] = float("nan")
            rows.append({"dimension": dim, "error": "unreadable frame"})
            continue
        net, gross = float(diff.sum()), float(diff.abs().sum())
        nets[dim] = net
        move_share = diff.abs() / gross if gross else diff.abs() * 0.0
        book_gross = float(prev.abs().sum())
        book_share = prev.abs() / book_gross if book_gross else prev.abs() * 0.0
        order = diff.abs().sort_values(ascending=False).index
        top = leaves.loc[order]
        rows.append({
            "dimension": dim,
            "divergence": round(float((move_share - book_share).abs().sum()) / 2, 4),
            "net": net, "gross": gross,
            "offset_ratio": round((gross - abs(net)) / gross, 4) if gross else 0.0,
            "top1_label": str(top[label_col].iloc[0]) if len(top) else "",
            "top1_share_gross": round(float(move_share.loc[order[0]]), 4) if len(order) else 0.0,
            "top1_share_net": round(float(diff.loc[order[0]] / net), 4) if len(order) and net else float("nan"),
            "top3_share_gross": round(float(move_share.loc[order[:top_n]].sum()), 4),
            "hhi_move": round(float((move_share ** 2).sum()), 4),
            "n_rows": int(len(leaves)),
        })
    valid = [v for v in nets.values() if v == v]  # drop NaNs
    reference = expected_net if expected_net is not None else (
        float(pd.Series(valid).median()) if valid else float("nan"))
    floor = max(abs(reference), 1.0)
    recon = pd.DataFrame([
        {"dimension": dim, "net": net, "deviation": net - reference,
         "ok": bool(net == net and abs(net - reference) <= rel_tol * floor)}
        for dim, net in nets.items()])
    table = pd.DataFrame(rows)
    if "divergence" in table.columns:
        table["reconciled"] = table["dimension"].map(
            recon.set_index("dimension")["ok"])
        table = table.sort_values(["divergence", "top1_share_gross"],
                                  ascending=False).reset_index(drop=True)
    ok_ranked = table[table.get("reconciled", False) == True]  # noqa: E712
    return {
        "table": table,
        "tables": {"reconciliation": recon},
        "reference_net": reference,
        "reconciled": bool(recon["ok"].all()),
        "top_dimension": str(ok_ranked["dimension"].iloc[0]) if len(ok_ranked) else "",
    }
