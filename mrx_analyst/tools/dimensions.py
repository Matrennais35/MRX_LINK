"""Dimension discovery — what MRX can actually break a question down by.

Parses the MRX reference tables (views/multirow/tables/*.md — the same files
the validation gate is built on) into a structured, queryable catalog of
dimensions, so the DataScout reasons over the REAL option list (Book, Deal,
Currency pair, Tenor, Desk, Portfolio, ...) instead of hallucinating codes.
Deterministic lookup only — no embeddings, no exemplars; the agent still does
the reasoning, this just tells it what exists.

Parsing is loud-by-construction: counts are asserted at first use, so an MRX
doc format change fails at startup with a clear message, not mid-answer with a
silently empty catalog.
"""

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import List, Optional

TABLES_DIR = Path(__file__).resolve().parent.parent / "views" / "multirow" / "tables"

# file -> (axis name, minimum plausible row count — assert catches doc drift)
_TABLE_SPECS = [
    ("row_selection.md", "row", 300),
    ("columns_selection.md", "column", 100),
    ("risk_type_selection.md", "risk_type", 60),
]

_ROW_RE = re.compile(r"^\|\s*(?P<display>[^|]+?)\s*\|\s*(?P<code>[^|]+?)\s*\|\s*$")


@dataclass(frozen=True)
class Dimension:
    display: str      # human name, e.g. "Deal/Security"
    code: str         # MRX code, e.g. "RowGrpPrdInlNo"
    axis: str         # "row" (p1217..p1759) | "column" (p1029) | "risk_type" (p13)


def _parse_table(path: Path, axis: str) -> List[Dimension]:
    dims = []
    for line in path.read_text(encoding="utf-8").splitlines():
        m = _ROW_RE.match(line)
        if not m:
            continue
        display, code = m.group("display"), m.group("code")
        # skip the header row and the |---|---| separator
        if set(code) <= {"-", " "} or code.lower().startswith(("code", "internal code")):
            continue
        dims.append(Dimension(display=display, code=code, axis=axis))
    return dims


@lru_cache(maxsize=1)
def all_dimensions() -> List[Dimension]:
    """Every dimension MRX offers, parsed once. Asserts plausible counts so a
    reference-doc format change is a loud startup failure."""
    dims: List[Dimension] = []
    for filename, axis, min_count in _TABLE_SPECS:
        path = TABLES_DIR / filename
        parsed = _parse_table(path, axis)
        if len(parsed) < min_count:
            raise AssertionError(
                f"dimension table {filename} parsed only {len(parsed)} rows "
                f"(expected >= {min_count}) — has its format changed?"
            )
        dims.extend(parsed)
    return dims


def find(term: str, axis: Optional[str] = None) -> List[Dimension]:
    """Dimensions whose display name or code contains `term` (case/space
    insensitive), optionally restricted to one axis. Deterministic substring
    match — used for validation and tests, not fuzzy semantics."""
    needle = re.sub(r"\s+", "", term.lower())
    hits = []
    for dim in all_dimensions():
        if axis and dim.axis != axis:
            continue
        hay = re.sub(r"\s+", "", (dim.display + dim.code).lower())
        if needle in hay:
            hits.append(dim)
    return hits


def catalog_text(axis: Optional[str] = None) -> str:
    """The compact 'display -> code' listing injected into the DataScout's
    prompt, grouped by axis — the agent picks breakdowns from what actually
    exists rather than inventing codes (validation still hard-rejects any
    code not in the tables, so this is belt AND braces)."""
    lines = []
    for ax, title in (("row", "ROW GROUPINGS (p1217..p1759 — what each row is)"),
                      ("column", "COLUMN GROUPINGS (p1029 — what the columns are; URL takes the Display Name)"),
                      ("risk_type", "RISK TYPES (p13)")):
        if axis and ax != axis:
            continue
        lines.append(f"## {title}")
        for dim in all_dimensions():
            if dim.axis == ax:
                lines.append(f"- {dim.display} -> {dim.code}")
        lines.append("")
    return "\n".join(lines)
