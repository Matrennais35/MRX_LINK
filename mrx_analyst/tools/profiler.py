"""Deterministic data profiling — what a fetched frame actually contains.

After every fetch, `profile(df)` produces a DataProfile: shape, the detected
value column(s), totals, sign mix, concentration (top-share/HHI) per low-
cardinality categorical, top absolute movers, date coverage. `render_text()`
is the compact form injected into agent prompts, so the orchestrator's next
decision — and the Analyst's tool choices — reason over a REAL summary of the
data instead of a 3-row sample. Pure pandas, no LLM, fully testable.

MRX-specific care: multirow frames often carry pre-aggregated "Total" rows and
wide date-columns layouts; totals are detected and excluded from statistics
(they'd double every sum and fake the concentration numbers).
"""

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

# Categorical columns with more distinct values than this get cardinality-only
# treatment (a concentration profile over 10k deals is noise, not signal).
MAX_CATEGORICAL_CARDINALITY = 50
TOP_MOVERS = 10

_DATE_COL_RE = re.compile(r"^\d{4}[-/]\d{2}[-/]\d{2}$")
_TOTAL_TOKENS = {"total", "grand total", "all", "depth 0"}


@dataclass
class CategoricalProfile:
    column: str
    n_unique: int
    top5_share: float          # share of total |value| in the 5 largest groups
    hhi: float                 # Herfindahl index over |value| shares (1.0 = one group)
    top_groups: List[str]      # the 5 largest group labels, largest first


@dataclass
class DataProfile:
    rows: int
    cols: int
    columns: Dict[str, str]                      # name -> dtype
    value_columns: List[str]                     # detected numeric measure column(s)
    date_columns: List[str]                      # wide-format date-named columns
    total_rows_excluded: int                     # pre-aggregated rows stripped from stats
    total_sum: Optional[float] = None            # net sum of the primary value column
    gross_positive: Optional[float] = None
    gross_negative: Optional[float] = None
    sign_mix: Optional[Dict[str, int]] = None    # {"pos": n, "neg": n, "zero": n}
    date_range: Optional[Dict[str, str]] = None  # {"min": ..., "max": ...}
    categoricals: List[CategoricalProfile] = field(default_factory=list)
    top_movers: List[Dict] = field(default_factory=list)  # [{label, value}] by |value|
    nulls: Dict[str, int] = field(default_factory=dict)

    def render_text(self) -> str:
        """The compact prompt-injectable summary (~<=40 lines)."""
        lines = [f"{self.rows} rows x {self.cols} cols"
                 + (f" ({self.total_rows_excluded} pre-aggregated Total row(s) excluded from stats)"
                    if self.total_rows_excluded else "")]
        lines.append("columns: " + ", ".join(f"{n}({t})" for n, t in list(self.columns.items())[:15])
                     + (" ..." if len(self.columns) > 15 else ""))
        if self.date_columns:
            lines.append(f"wide date columns: {self.date_columns[0]} .. {self.date_columns[-1]} "
                         f"({len(self.date_columns)} dates)")
        if self.value_columns:
            lines.append(f"value column(s): {', '.join(self.value_columns)}")
        if self.total_sum is not None:
            lines.append(f"net sum: {self.total_sum:,.0f}  "
                         f"(gross +{self.gross_positive:,.0f} / {self.gross_negative:,.0f})")
        if self.sign_mix:
            lines.append(f"sign mix: {self.sign_mix['pos']} positive / {self.sign_mix['neg']} negative "
                         f"/ {self.sign_mix['zero']} zero rows")
        if self.date_range:
            lines.append(f"date range: {self.date_range['min']} .. {self.date_range['max']}")
        for cat in self.categoricals:
            lines.append(f"by {cat.column}: {cat.n_unique} groups, top-5 hold {cat.top5_share:.0%} "
                         f"of |value| (HHI {cat.hhi:.2f}); largest: {', '.join(cat.top_groups[:3])}")
        if self.top_movers:
            movers = "; ".join(f"{m['label']}: {m['value']:,.0f}" for m in self.top_movers[:5])
            lines.append(f"top movers by |value|: {movers}")
        nulls = {k: v for k, v in self.nulls.items() if v}
        if nulls:
            lines.append("nulls: " + ", ".join(f"{k}={v}" for k, v in list(nulls.items())[:6]))
        return "\n".join(lines)


def _is_total_label(value) -> bool:
    return isinstance(value, str) and value.strip().lower() in _TOTAL_TOKENS


def profile(df: pd.DataFrame) -> DataProfile:
    """Profile a fetched frame. Never raises on odd frames — every section
    degrades to absent rather than failing the fetch that produced it."""
    columns = {str(c): str(t) for c, t in df.dtypes.items()}
    date_columns = [str(c) for c in df.columns if _DATE_COL_RE.match(str(c))]

    # Strip pre-aggregated Total rows (any object column carrying a total token)
    # before statistics — they double sums and fake concentration.
    object_cols = [c for c in df.columns if df[c].dtype == object]
    total_mask = pd.Series(False, index=df.index)
    for c in object_cols:
        total_mask |= df[c].map(_is_total_label).fillna(False)
    body = df[~total_mask]

    numeric_cols = [str(c) for c in body.columns
                    if pd.api.types.is_numeric_dtype(body[c]) and str(c) not in date_columns]
    # The primary measure: the numeric column with the largest absolute mass
    # (MRX frames often carry ids/levels as numerics; risk values dominate).
    value_columns: List[str] = []
    if numeric_cols:
        mass = {c: float(body[c].abs().sum()) for c in numeric_cols}
        value_columns = [max(mass, key=mass.get)] if any(mass.values()) else []

    prof = DataProfile(
        rows=len(df), cols=df.shape[1], columns=columns,
        value_columns=value_columns, date_columns=date_columns,
        total_rows_excluded=int(total_mask.sum()),
        nulls={str(c): int(df[c].isna().sum()) for c in df.columns},
    )

    if value_columns and len(body):
        v = body[value_columns[0]].dropna()
        prof.total_sum = float(v.sum())
        prof.gross_positive = float(v[v > 0].sum())
        prof.gross_negative = float(v[v < 0].sum())
        prof.sign_mix = {"pos": int((v > 0).sum()), "neg": int((v < 0).sum()),
                         "zero": int((v == 0).sum())}

    # Date coverage from either a datetime column or wide date-named columns.
    dt_cols = [c for c in body.columns if pd.api.types.is_datetime64_any_dtype(body[c])]
    if dt_cols:
        s = body[dt_cols[0]].dropna()
        if len(s):
            prof.date_range = {"min": str(s.min().date()), "max": str(s.max().date())}
    elif date_columns:
        prof.date_range = {"min": min(date_columns), "max": max(date_columns)}

    # Concentration per low-cardinality categorical, weighted by |value|.
    if value_columns and len(body):
        absval = body[value_columns[0]].abs()
        grand = float(absval.sum())
        for c in object_cols:
            groups = body.groupby(c, dropna=True)[value_columns[0]].apply(lambda s: float(s.abs().sum()))
            n_unique = int(body[c].nunique(dropna=True))
            if n_unique == 0 or n_unique > MAX_CATEGORICAL_CARDINALITY or grand == 0:
                continue
            shares = (groups / grand).sort_values(ascending=False)
            prof.categoricals.append(CategoricalProfile(
                column=str(c), n_unique=n_unique,
                top5_share=float(shares.head(5).sum()),
                hhi=float((shares ** 2).sum()),
                top_groups=[str(g) for g in shares.head(5).index],
            ))

        # Top movers: largest |value| rows, labelled by the object columns.
        if len(body):
            idx = absval.sort_values(ascending=False).head(TOP_MOVERS).index
            for i in idx:
                label = " / ".join(str(body.at[i, c]) for c in object_cols[:3]) or f"row {i}"
                prof.top_movers.append({"label": label,
                                        "value": float(body.at[i, value_columns[0]])})

    return prof
