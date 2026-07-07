---
name: mrx_reading
when_to_use: Writing analysis code over fetched MRX frames — the shapes and the traps that produce silently-wrong numbers.
examples:
  - "sum doubled -> Depth ancestors duplicate children; use leaf rows"
  - "where's the value column in a history frame -> the dates ARE the columns"
---

# Reading MRX frames

## The four shapes you will meet
- HISTORY (wide): label column(s) + one column PER DATE ("2026/07/03"...).
  No standing value column — latest date column = current level. Melt to long
  for trends; `helpers.ops.trend(df)` gives dated jumps + the long series.
- COMPARE: `Total`, `Total (prv)`, `Total (diff)` columns — use them
  directly, never recompute the diff.
- EXPLAIN: `Depth`, explain-cause label (New / Passive / Expired), risk
  component, + compare columns. Components sum to the explained move — verify
  the reconciliation and say so in the note.
- HIERARCHY: any multi-level request -> `Depth` int + ONE label column
  (deepest level per row). ANCESTOR ROWS DUPLICATE CHILD SUMS — summing all
  rows double-counts. `helpers.ops.leafify(df)` keeps leaf rows; every
  helpers op applies it automatically.

## The traps
- "Total" rows: pre-aggregated — exclude from statistics (profiler already
  flags them).
- Deal labels carry structure — "FXO-1857297/4 | FXO STND Put 2027-05-19" =
  deal/leg | instrument | MATURITY DATE. previous=0 -> NEW position;
  current=0 -> closed (expired when maturity <= COB else unwound);
  `helpers.ops.position_change` classifies all of it.
- A 1x1 frame with an 'Invalid Parameters' column is a FAILED fetch (the tool
  raises it — you will never see one, but never analyze one either).
- UNITS: values are as-reported (no currency conversion exists). State
  figures in reported units with the COB window.
- Scenario/ladder frames (e.g. PV across spot shifts): not yet documented —
  when you meet one, read the columns carefully and note the shape in the
  answer.
