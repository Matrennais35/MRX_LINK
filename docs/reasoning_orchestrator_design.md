# Design: the reasoning orchestrator (plan → investigate-with-depth → critique)

Status: **design pass, not yet built.**

## Intent

Not example-matching / RAG (explicitly rejected). The orchestrator must
*reason*, freshly, every question: what is the user actually trying to learn
(the **target**)? What breakdown would reveal it? Is what I have enough? Is
this the right representation? — and drive fetches/views/output from that
reasoning, not from a retrieved template.

Three reasoning moments, composed into one loop:
1. **Plan** — reason about target → breakdown → representation *before* fetching.
2. **Investigate with depth** — each step argues target/sufficiency/what-more.
3. **Critique** — judge the answer against the target, refine if it falls short.

All three preserve the properties that must not change: bounded fetches (hard
cap), every fetch validation-gated and logged, one auditable trace.

## The current shape (what we build on)

`run_agent_loop` is already staged: `_load_context` → `_investigate` (the
decide→fetch loop) → `_answer`. The one LLM decision per step is
`decide_next_step` returning `StepDecision{action, reasoning, fetch_query}`.
Today that decision is shallow and one-shot; there's no up-front plan and no
post-answer critique.

## 1. Plan — an explicit up-front analysis plan (new STAGE 0.5)

Before the investigate loop, ONE new reasoning call: `plan_analysis(llm,
query, gathered, history) -> AnalysisPlan`.

```python
class AnalysisPlan(BaseModel):
    target: str            # what the user is really trying to learn — the
                           # question behind the question ("which book/deal
                           # drove the FX Vega increase, and is it concentrated")
    approach: str          # the reasoned plan: what breakdown(s), in what
                           # order, and WHY each reveals the target
    representation: str    # how the answer should be shown to best serve the
                           # target — "waterfall of contributions", "ranked
                           # table + bar", "evolution line", "single number"
    success_criteria: str  # what a GOOD answer must contain — used later by
                           # the critique step as the rubric (self-set target)
```

- This is a genuine reasoning artifact, shown to the user (it IS the "deep
  think before scratching the view" they asked for) and persisted in the trace.
- It's a PLAN, not a script: the investigate loop still adapts to what each
  fetch returns. The plan sets direction and the success criteria; it does not
  hard-code the fetches. (Evidence: rigid up-front plans are strictly worse
  than an adaptive loop — this stays adaptive.)
- The plan is threaded into every downstream call: `decide_next_step` sees the
  target+approach (so fetches serve the plan), the answer stage sees the
  representation (so the chart/format fits), and critique sees success_criteria.

## 2. Investigate with depth — richer per-step reasoning

`StepDecision` gains fields that force the deeper argument at each step
(reasoning threaded, not a separate call — deepening the existing loop is
better-evidenced than adding a rigid planner):

```python
class StepDecision(BaseModel):
    action: Literal["fetch", "analyze", "respond"]
    target_progress: str   # NEW: what the gathered data now shows toward the
                           # target, and what's still MISSING to answer it well
    reasoning: str         # why THIS action follows from that gap
    fetch_query: str
```

`decide_next_step` is given the `AnalysisPlan` and must argue each step against
the target: "by-book shows the net but not which deals within the top book —
still missing the deal-level drill to answer 'what drove it', so fetch that."
This is where "is what I have enough / what would reveal more" lives.

## 3. Critique — a target-anchored quality gate (new final stage)

After the answer is produced, ONE critique call: `critique_answer(llm, query,
plan, answer) -> Critique`.

```python
class Critique(BaseModel):
    answers_the_target: bool   # does it actually address plan.target?
    meets_criteria: bool       # does it satisfy plan.success_criteria?
    right_representation: bool  # is the chart/format the best for the target?
    gaps: str                  # specific, concrete shortfalls (empty if none)
    verdict: Literal["deliver", "refine"]
```

- **Anchored, not open-ended.** The research is explicit: open-ended "improve
  this" self-critique DEGRADES quality; gains require a verifiable anchor. Here
  the anchor is `plan.success_criteria` (the model's own up-front target) AND
  the computed table (does the narrative match the numbers). The critique
  checks the answer against those, not against vibes.
- **Capped at ONE refine.** On "refine", the answer stage re-runs ONCE with the
  named gaps as guidance, then delivers regardless. No unbounded critique loop.
- Cheap escape: critique never raises; on any failure it delivers the answer
  as-is (a critique hiccup must not lose a computed answer).

## 4. Smart views from the target (representation)

The `representation` field from the plan flows into the code-gen prompt: the
model is told what representation the plan called for (waterfall / ranked
table+bar / line / number) and should produce THAT, rather than defaulting to a
generic bar. This is the reasoning-driven version of "smart views depending on
the target" — the orchestrator *decides* the representation as part of
planning, and the code-gen executes that decision. (No rule table; the plan's
reasoning chooses it.)

## The loop, end to end

```
_load_context                 # prior data + history (STAGE 0)
plan = plan_analysis(...)     # NEW: target, approach, representation, criteria
_investigate(plan=plan, ...)  # decide→fetch loop, each step argues vs. target
answer = _answer(plan=plan)   # analyze/respond, representation from the plan
crit = critique_answer(...)   # NEW: judge vs. target+criteria+table
if crit.verdict == "refine":  # ONE bounded refine pass
    answer = _answer(..., refine_guidance=crit.gaps)
return LoopResult(answer, views, steps, plan, critique)   # plan+critique added
```

## What stays fixed (non-negotiable, unchanged)

- Hard fetch cap, validation gate on every fetch, one auditable trace.
- The adaptive after-seeing-data loop (plan sets direction, doesn't script).
- No exemplars/RAG. All quality comes from the orchestrator REASONING, not
  from retrieved examples.
- No concurrent/ensemble agents (worst ROI here; stresses the cap/audit).

## Cost, honestly

Adds 2 LLM calls per question (plan + critique), plus up to 1 refine re-run.
For a multi-step analytical question that already makes 4-6 calls, that's a
~30-50% call increase — and every call is at reasoning_effort=high. This is the
deliberate trade: more deliberation for better answers, on a tool where quality
matters more than latency. The plan/critique calls are skippable for trivial
lookups (a "respond" or single-number path doesn't need a plan) — gate them so
they only fire for genuinely analytical questions.

## Build order (each independently testable)

1. **Plan stage** — `AnalysisPlan` + `plan_analysis`, threaded into
   `decide_next_step` and the answer stage. Biggest single lever (the "deep
   think + target + smart representation" the user asked for).
2. **Deeper step reasoning** — add `target_progress` to `StepDecision`, give the
   plan to `decide_next_step`.
3. **Critique stage** — `Critique` + `critique_answer` + the one bounded refine.
4. **Wire plan+critique into the UI trace and persistence.**

Verification per stage: existing tests stay green (additive), plus new tests
that the plan is produced and threaded, the step reasons against the target,
and the critique gate refines exactly once then delivers.
