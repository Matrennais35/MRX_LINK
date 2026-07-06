# Design: restructure — same idea, one shape, fewer calls, deeper analysis

Status: **design pass, not yet built.**

## Diagnosis (measured, not felt)

The pipeline's *flow* is right (context → plan → investigate → compute →
interpret). The complexity is **shape proliferation**, accreted one feature at
a time:

| Symptom | Measure |
|---|---|
| Four prose systems in `smart_pandas.py` | `_narrate`, `synthesize`, `respond`, composed-inline — 579 lines |
| Five-way answer union | `number\|string\|dataframe\|chart\|composed`, branched at **16 sites** |
| Two step-record types | `StepRecord` (memory) vs `StepTrace` (persisted) + a manual converter |
| Three callback channels | `on_stage`/`on_step`/`on_token` — 23 refs in loop.py alone |
| Parameter threading | `plan=None`, `history=()`, `gathered`, 3 callbacks through every signature |
| app.py = 602 lines | shell + 5-type rendering + feedback UI + scroll JS, one file |

Each was locally reasonable. The sum is what "too complex" feels like.

## The restructure (not a rewrite)

The validated primitives stay byte-identical: the exec sandbox, the validation
gate, the catalog SQL, the deterministic reuse fingerprint, the View protocol,
the fetch cap. What changes is the SHAPES around them.

### 1. ONE answer shape (kills the 5-way union and 2 of 4 prose paths)

```python
@dataclass
class Answer:
    narrative: str                    # ALWAYS present — every answer explains itself
    value: Any = None                 # a scalar, when the question was a lookup
    table: pd.DataFrame | None = None # the structured breakdown, when data was computed
    chart: Figure | None = None       # the visualization, when one serves the target
    method: str = ""
    code: str = ""
```

- Today's `composed` becomes the ONLY shape; the other four collapse into it
  (a number answer = narrative + value; a plain chart = narrative + chart).
- **Analysis increase for free:** today only `composed` answers get the
  analyst synthesis and can carry table+chart together — a `string`/`number`
  answer gets the weak old narration and can never attach a chart. With one
  shape, EVERY data answer gets synthesis and can carry any artifact the
  target deserves.
- Rendering/persistence stop branching 5 ways: render narrative, then each
  part that exists. 16 branch sites → ~4.

### 2. TWO prose paths, in their own module (kills smart_pandas' overload)

```
compute.py  — code-gen + exec sandbox + result validation   (from smart_pandas)
narrate.py  — synthesize(question, table|value) → narrative  (data answers)
              respond(question, history, descriptions)       (no-data answers)
```

`_narrate` and the composed-inline narrative are deleted; `synthesize` (the
good, analyst-grade path) serves every computed answer. One system prompt for
each of the two genuinely different jobs: interpret data / answer in prose.

### 3. Merge plan + first decision (efficiency: one fewer LLM call, every question)

The plan already reasons "target → approach → first thing to look at" — then we
immediately ask `decide_next_step` what to do first, which re-derives it. The
plan call now ALSO returns the first action:

```python
class AnalysisPlan(BaseModel):
    target / approach / representation / success_criteria   # unchanged
    first_action: Literal["fetch", "analyze", "respond"]
    first_fetch_query: str = ""
```

Typical question: 5 LLM calls → 4 (plan, [decide]×(n-1), code-gen, synthesize).
Trivial "respond" question: 2 calls (plan says respond → respond). Subsequent
steps keep the adaptive `decide_next_step` exactly as-is.

### 4. RunContext (kills parameter threading)

```python
@dataclass
class RunContext:
    query: str
    plan: AnalysisPlan | None
    views: list[ViewResult]          # gathered so far (seeded from catalog)
    history: list[Turn]
    steps: list[Step]                # the audit trace, one record type
    emit: Callable                   # ONE event channel (see 5)
    session_id: str; conversation_id: str | None
```

Stages take `(llm, ctx)` instead of eight kwargs. The loop reads as five lines.

### 5. ONE event channel (kills 3 callback channels)

`emit(kind, payload)` with kinds `"stage" | "step" | "token"`. The app installs
one handler and routes by kind. `on_stage`/`on_step`/`on_token` deleted.

### 6. ONE step record (kills StepRecord/StepTrace + converter)

A single `Step` dataclass used in memory AND persisted (catalog takes/returns
it directly). `steps_to_traces` deleted.

### 7. UI split (app.py 602 → ~3 focused files)

```
app.py       — shell: identity, sidebar, chat loop           (~200 lines)
ui_render.py — render Answer / plan / trace / source data    (~200 lines)
ui_feedback.py — feedback form + log viewer                  (~80 lines)
```

(Flat files next to app.py, not a package — Streamlit runs app.py as a script.)

### Resulting layout

```
mrx/
  pipeline/
    loop.py        ~150   orchestration only: context→plan→investigate→answer
    planner.py     ~180   AnalysisPlan + plan_analysis + decide_next_step
    compute.py     ~200   code-gen + exec sandbox (unchanged logic)
    narrate.py     ~120   synthesize + respond
    answer.py      ~40    the one Answer dataclass
    fetch.py       unchanged
    router.py      unchanged
    catalog.py     ~450   (Step unification trims it)
    feedback.py    unchanged
  views/           unchanged
app.py / ui_render.py / ui_feedback.py
```

Net: ~3,400 → ~2,600 lines, one answer shape, two prose paths, one event
channel, one step record, one fewer LLM call per question.

## Where "increasing the analysis" comes from (not just tidiness)

1. **Synthesis becomes universal** — every computed answer gets the analyst
   treatment (BLUF, drivers, concentration-vs-offsetting), not just the ones
   the model happened to tag `composed`.
2. **Representation becomes universal** — any answer can carry the chart the
   plan called for; today a `number`-typed answer physically can't.
3. **The critique stage (docs/reasoning_orchestrator_design.md) drops in
   cleanly**: one shape to critique against `success_criteria` + the table,
   instead of five.

## Migration (staged, tests green at every step — NOT a big-bang rewrite)

1. `Answer` + collapse code-gen output to it; adapt renderers/persistence.
   (Biggest step; the 16 branch sites shrink here.)
2. Split `smart_pandas.py` → `compute.py`/`narrate.py`; delete `_narrate`.
3. Merge plan+first-decision; delete the redundant first `decide` call.
4. `RunContext` + single `emit` channel; collapse signatures.
5. Unify `Step`; delete `steps_to_traces`.
6. Split app.py → ui_render/ui_feedback.
7. Sweep: delete dead prompts/paths, update docs.

Each step is independently shippable and test-verified. Catalog schema is
unchanged except `answer_type` values (existing rows still render: old type
strings map onto the parts-present logic).

## Not doing

- Not touching fetch/validation/reuse/View — proven, already clean.
- Not an agent framework, not exemplars, not multi-agent (all previously
  settled with evidence).
- Not renaming for its own sake — only where a shape merges.
