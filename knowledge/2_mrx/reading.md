---
name: mrx_reading
when_to_use: Writing analysis code over fetched MRX frames — how to read them correctly.
examples:
  - "Why does my sum double-count? (Depth ancestors)"
  - "Where is the value column in a history frame? (dates ARE the columns)"
---

# Reading MRX frames (the traps that produce silently-wrong numbers)

- WIDE HISTORY FRAMES: dates are the COLUMNS (e.g. "2026/07/03"). There is no
  single value column; the latest date column is the current level; melt to
  long format for trends. `helpers.trend(df)` does the dated-jumps analysis.
- DEPTH HIERARCHIES: multi-level views return a `Depth` int column + ONE label
  column (the deepest level's label per row). ANCESTOR ROWS DUPLICATE THEIR
  CHILDREN'S SUMS — summing all rows double-counts. Group over leaf rows only
  (`helpers.leafify(df)`; all helpers ops do this automatically).
- TOTAL ROWS: frames may carry pre-aggregated "Total" rows — exclude from
  statistics.
- COMPARE FRAMES: columns are `Total`, `Total (prv)`, `Total (diff)` — use
  them directly; don't recompute diff.
- DEAL LABELS: carry structure — "FXO-1857297/4 | FXO STND Put 2027-05-19":
  deal id/leg, instrument, and the MATURITY DATE. previous=0 rows are NEW
  positions; current=0 rows are closed (expired when maturity <= COB, else
  unwound) — `helpers.position_change` classifies this.
- ERROR FRAMES: a 1x1 frame with an 'Invalid Parameters' column is a FAILED
  fetch (the tool raises it; never analyze it).
- UNITS: values are as-reported by MRX (no currency conversion available) —
  state figures in reported units, with the COB window.
