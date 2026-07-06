# Design: composed answers (narrative + table + chart)

Status: **design pass, about to build.**

## Problem

An analytical question ("analyse the variation, what drove it") today returns
ONE result — usually `type="string"` with the whole multi-part analysis crammed
into a single prose blob. It reads as a wall of text, and different aggregations
(by portfolio×pair vs by pair vs by portfolio) look contradictory because
nothing labels or separates them. The user wants: a short explanation, a
structured table, and a chart — together.

## Approach: a new `"composed"` result type (additive)

`smart_pandas`'s code-gen can already return `number | string | dataframe |
chart`. Add one more:

```python
result = {"type": "composed", "value": {
    "narrative": "<short markdown explanation — headline + what drove it>",
    "table": <a pandas DataFrame, or None>,     # e.g. top contributors
    "chart": <a matplotlib Figure, or None>,    # e.g. contribution bar chart
}}
```

At least one of table/chart should be present (else it's just a string answer).
The narrative is written BY the code-gen step (it has the actual numbers), not
by the separate narration LLM call — see below.

Existing types are untouched: a lookup still returns `number`, a plain plot
still returns `chart`. `composed` is only chosen for genuinely multi-part
analytical questions. The prompt steers this.

## Changes, by file

### `smart_pandas.py`
- **SYSTEM_PROMPT**: add the `composed` shape + when to use it ("for an
  analysis that benefits from a short explanation, a summary table of the key
  breakdown, and a chart — e.g. 'what drove the variation'"). Tell it to label
  aggregations clearly in the narrative (this is what fixes the "USDEUR vs
  USDHKD looks contradictory" confusion — the narrative must say "by
  portfolio×pair … vs pooled by pair …").
- **`_run_code`**: validate a `composed` result — `value` is a dict; if
  `chart` is present it must be a live Figure (reuse the existing Figure
  check); `table` if present must be a DataFrame; require at least one of
  them. Close non-returned figures as today.
- **`ask`**: for a `composed` result, DON'T run the narration LLM call — the
  narrative is already in the value. Set `AnswerResult.narration` = the
  value's narrative, `method`/`code` as usual. (Every other type still
  narrates exactly as now.)
- **`_describe_value`** (used for fallback/preview): describe a composed
  result as "an analysis with a narrative" + table shape + chart title.

### `app.py`
- **`_render_live_answer`**: render `composed` as sections — the narrative
  (markdown), then the chart (`st.pyplot`) if present, then the table
  (`st.dataframe`) if present. Other types render exactly as today.
- **`_value_preview`** / catalog `answer_type`: a composed turn stores
  `answer_type="composed"` and a short `value_preview` ("analysis + table +
  chart"); on reload the narrative (saved as `narration`) still shows, with a
  caption that the table/chart aren't replayed (same stance as chart/dataframe
  today — a Figure isn't SQLite-storable).
- **`_render_past_turn`**: show the saved narration for a composed turn (its
  table/chart aren't replayed, same as chart/dataframe).

## Not changing

- The loop, the orchestrator's analyze/respond/fetch decision, the catalog
  schema (composed reuses the existing `narration`/`answer_type`/`value_preview`
  columns — no migration).
- The narration prompt for non-composed types.

## Verification

- `smart_pandas` tests: a composed result round-trips (narrative + table +
  chart), validation rejects a composed with neither table nor chart, and a
  composed result is NOT re-narrated (its narrative passes through).
- `app` test (AppTest): a composed answer renders a chart AND a dataframe AND
  the narrative text, in one turn.
- All existing tests stay green (composed is additive).
