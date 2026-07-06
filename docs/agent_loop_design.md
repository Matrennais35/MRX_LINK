# Design: bounded controller loop for the MRX pipeline

Status: **design pass, not yet built.** This is the shape we agreed to
before writing any code. Nothing in `mrx/pipeline/` changes until this is
signed off.

## The decision already made

- **Sequential bounded loop, not parallel multi-agent fan-out.** The
  flagship case ("check FX Vega by desk → see one desk dominates → drill
  into that desk's deals") is dependency-chained: each fetch's parameters
  depend on the previous fetch's result. Parallelism doesn't help that;
  it only helps the narrower "N independent views known up front" case,
  which the *existing* `multi_fetch` mode already covers.
- **Hand-rolled, not LangGraph / Pydantic AI / AgentExecutor.** Research
  came back clear: LangGraph's iteration cap (`recursion_limit`) has had
  its default changed twice in 2026 and counts graph super-steps, not tool
  calls — an unreliable foundation for the one guarantee that matters most
  here (bounding calls into a production risk system). The "mandatory
  validation gate" requirement doesn't favor a framework: in every option
  the gate is just code that runs before the tool executes. Anthropic's own
  "Building Effective Agents" puts a fixed, capped, gated loop like this in
  *workflow* territory, where direct code beats a framework. We already have
  `.with_structured_output()` wired in — the loop is ~40-80 lines of plain
  Python.

## What exists today (verified against the code, not memory)

`orchestrator.run()` decides the *entire* shape of a question up front:

1. If `allow_multi_fetch`, one `router.route()` call classifies the
   question into `answer_from_context | single_fetch | multi_fetch` — this
   is decided **before any data is seen**.
2. Then it executes that fixed plan: 0 fetches (answer_from_context), 1
   (single), or N concurrent (multi).
3. `smart_pandas.ask()` runs **once**, read-only over whatever
   dataframe(s) it was handed. It can compute and narrate; it **cannot
   request more data.**

The only existing "loop" is `_plan_and_validate`'s retry-on-validation-
error (lines 56-82) — that's forced error-correction, *not* the model
choosing to iterate. So the max fetches for one question is fixed the
instant `route()` returns, and no later stage can revise it. **That fixed-
before-seeing-data property is exactly what "too static" means.**

## The change in one sentence

Replace "decide the whole shape once, then execute" with "decide **one
step** at a time, look at the result, then decide the next step" — capped
at a hard maximum number of fetches, every fetch still gated by
`validation.validate_plan`, every step recorded.

## The loop

```
run_agent_loop(llm, query, *, max_fetches=5, ...):
    state = LoopState(query=query, steps=[], datasets=[])   # datasets = ViewResults gathered so far

    for step_num in range(1, max_steps + 1):
        decision = decide_next_step(llm, state)      # ONE structured-output call
        record(state, decision)                       # for the audit trail / "how was this computed"

        if decision.action == "answer":
            break                                     # model says it has enough

        if decision.action == "fetch":
            if fetches_done(state) >= max_fetches:    # HARD CAP — checked in our code, not the model's
                # model wanted more data but we won't allow it; answer with what we have
                break
            view = _get_view(llm, decision.fetch_query, ...)   # REUSE existing stage: plan→validate→reuse-or-fetch
            state.datasets.append(view)               # validation.validate_plan already ran inside _get_view
            continue

    # loop exhausted or model chose to answer → single answer pass over everything gathered
    answer = smart_pandas.ask(<all state.datasets>, query, llm, ...)   # REUSE existing answer stage
    return PipelineResult(...)
```

Everything in `_get_view` (plan → `validate_plan` → deterministic
reuse-check → fetch → catalog-save) is **reused unchanged**. The loop
doesn't add a new fetch path or a new validation path — it just calls the
existing one more than once, driven by the model instead of by a fixed
count from `route()`.

## The per-step decision (the one new LLM call)

A new structured-output schema, in the same spirit as `RoutingDecision`:

```python
class StepDecision(BaseModel):
    action: Literal["fetch", "answer"]
    reasoning: str                      # WHY — persisted for audit (see below)
    fetch_query: str = ""               # natural-language sub-question when action=="fetch";
                                        # fed to the EXISTING _get_view/get_link pipeline unchanged
```

The prompt gives the model: the original question, and a summary of what's
been gathered so far (each dataset's description + columns + a small
sample or key stats — **not** raw full data, same as how `route()` is
handed descriptions, not data). The model answers: "I have enough, answer
now" or "I need this specific additional cut, fetch it." `fetch_query` is
an ordinary NL sub-question — it goes through the *exact same*
`get_link → validate_plan` path every fetch already uses, so a bad/unsafe
URL is caught by the same gate, whether the model asked for it in step 1
or step 4.

## The two hard guarantees, and where they live in code

1. **Fetch cap.** A literal `max_fetches` int checked in *our* loop code
   (`if fetches_done(state) >= max_fetches: break`) — not a parameter
   handed to the model, not a framework setting. The model can *want* more;
   the loop simply stops calling `_get_view`. Immune to the LangGraph
   super-step drift problem because it counts actual `_get_view` calls.

2. **Validation gate.** Unchanged and non-bypassable: every fetch still
   goes through `_get_view` → `_plan_and_validate` → `validation.validate_plan`.
   The model choosing *what* to fetch never lets it choose an *unvalidated*
   fetch — the gate is downstream of the decision, in code the model can't
   route around.

## Auditability (this touches a bank's risk system)

`catalog.py` already records *what* was fetched. The loop adds a record of
*why* each step was taken — `state.steps` holds every `StepDecision`
(action + reasoning + fetch_query) in order. That trace is what feeds a
"how was this computed" view: not just "here's the data and answer," but
"step 1 fetched by-desk because X; step 2 drilled into DESK_A's deals
because by-desk showed DESK_A dominated; step 3 answered." Open question
below on how durably that trace needs to persist.

## What stays exactly as-is

- `validation.py`, `data_fetch.py`, `catalog.py`, `smart_pandas.ask` —
  untouched. The loop composes them; it doesn't rewrite them.
- The fast path. `allow_multi_fetch=False` callers (CLI, simple
  programmatic use) don't enter the loop at all — same single plan→fetch→
  answer they run today. The loop is opt-in exactly like `route()` is now.
- `answer_from_context` and deterministic reuse — both still apply *inside*
  each loop step (a step that asks for data already in the catalog reuses
  it, no MRX call), so the loop doesn't re-fetch what it already has.

## How the tests change (flagged honestly)

Several current tests assert *exact* fetch counts ("multi_fetch runs
exactly 3 fetches", "route() called exactly once"). A model-driven loop
makes the count variable, so those become **invariant** tests instead:
- never more than `max_fetches` fetches, for any question
- every fetch that happens passed `validate_plan` (the gate always ran)
- the loop always terminates (never exceeds `max_steps`)
- a model that says "answer" on step 1 does exactly 0 fetches and 1 answer
This is real rework, not free — but it's a shift in *what* we assert, not a
loss of coverage.

## Decisions (settled)

1. **`max_fetches` = plain count cap, start at 4.** Per-fetch *cost* is not
   predictable (a deal/row-level "fetch all deals" is far heavier than a
   node-level fetch), so a count cap doesn't distinguish cheap from
   expensive fetches — accepted for v1. Rationale: a count cap is the
   simplest thing that's provably bounded and trivially auditable ("never
   more than 4 MRX calls per question"). Guarding the specifically-expensive
   deal-level drill-down is a **known follow-up**, deliberately NOT built
   now — we don't yet have real data on how often the loop even *wants* a
   deal-level fetch, and guarding an unobserved cost is premature. Revisit
   once real usage shows deal-level drill-downs are common.

2. **Loop subsumes routing (Option A) — CONFIRMED.** `router.route()`'s
   three-way classification collapses into the per-step `StepDecision`:
   step 1 answers-from-context, fetches once, or fetches the first of
   several, and the loop continues from there. `answer_from_context` and
   deterministic reuse still apply *inside* each step (a step needing no new
   fetch just reuses), so no reuse behavior is lost — it stops being an
   up-front mode and becomes "a step that needs no new fetch."
   `route()` retires as the entry decision; its helper
   `find_reusable_dataset` (the deterministic reuse gate) **stays**, still
   called inside `_get_view`.

3. **Audit trace: UI + persisted — CONFIRMED.** `state.steps` (each step's
   action + reasoning + fetch_query, in order) is both shown live in the UI
   *and* persisted to the catalog per answer — a schema addition (a `steps`
   table, or a steps column on the existing `turns` table) recording the
   full "why each fetch happened" chain so a reviewer can reconstruct an
   answer's reasoning after the fact, not just its data. Compliance-grade
   "how was this computed."

## Verified (open question #4 — resolved, not a blocker)

**Answer over accumulated drill-down data: works today, improves with a
small, free addition.** Checked empirically (fake frames through the real
`sanitize_names` + `_describe_datasets`): a parent "by desk" frame and a
child "DESK_A by deal" frame arrive with correct names/columns/samples and
the model *can* answer over them. The gap: `_describe_datasets` presents
frames as a flat list with **no statement of how they relate** — the model
must *infer* that the child is the parent's DESK_A row drilled open, from
names + overlapping values. Usually correct on tidy data, less reliable on
messy real data — and for a drill-down the parent→child relationship is the
whole point of the answer.

**Fix (small, doesn't touch the loop):** thread a one-line *provenance* per
frame into the "Available data" block — `` `name` (fetched because:
<fetch_query/reasoning>): <schema> ``. The loop already produces exactly
this (`StepDecision.reasoning` / `fetch_query`, persisted for audit), so
**the audit trail and the answer-quality fix are the same data, used
twice.** Build this into the answer stage as part of wiring the loop, not
as a separate step.
```
