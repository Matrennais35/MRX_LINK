# Design: the View interface (make MRX views plug in, not hard-import)

Status: **built.** `mrx/views/base.py` (the `View` protocol), `mrx/views/
multirow/view.py` (`MultirowView`, the first implementation, delegating to the
existing generate_link/validation/data_fetch), and `mrx/views/__init__.py`
(the `REGISTRY` + `DEFAULT_VIEW`) exist. `fetch`/`router`/`loop` take a `View`
(defaulting to `DEFAULT_VIEW`) and no longer import a concrete view. Verified:
all prior tests green, plus `tests/test_views.py` runs a non-MRX `FakeView`
end-to-end through the loop, proving the seam is real.

## Goal

Adding a second MRX view (a different MRX report type) should be "write a new
View + register it" — zero edits to the loop, `fetch`, `router`, `catalog`,
or `smart_pandas`. Today the single view is hard-wired by import in exactly
two files, which is the real ceiling on "scale to more views."

## Scope decision (settled)

- **Build `View`, not `Source`.** A source-agnostic abstraction (SQL / file /
  API inputs) was considered and **deferred** — non-MRX input is only a
  "maybe", and building for it now means a source-agnostic catalog we don't
  need. `View` stays MRX-flavored: it may traffic in `MRXPlan`/URLs directly.
- **But keep View's *shape* = a future Source's shape** (plan / validate /
  execute / fingerprint). If a non-MRX source ever becomes real, `View`
  widens into `Source` by loosening types — not a redesign. This is the one
  bit of forethought we spend; everything else stays as concrete as today.

## The seam (verified against the code)

The entire view-coupling is **three call sites**:
- `fetch.plan_and_validate` → `generate_link.get_link` (plan) +
  `validation.validate_plan` (validate)
- `fetch.get_view` → `data_fetch.fetch_data(plan.url)` (execute)
- `router._covers` → `validation.parse_mrx_url` (fingerprint, for reuse-match)

Nothing else in the core knows which view it's running. `smart_pandas`
already operates on plain DataFrames (view-agnostic). `catalog` stores
`MRXPlan` as `plan_json` — that stays; `View` keeps producing `MRXPlan`, so
the catalog schema does **not** change (this is the payoff of not doing
`Source` now).

## The interface

```python
class View(Protocol):
    name: str                                   # registry key, e.g. "multirow"
    description: str                            # what this view answers — for
                                                # the loop/router to pick it

    def plan(self, llm, query, *, prior_attempts) -> MRXPlan: ...   # get_link
    def validate(self, plan, *, min_confidence) -> None: ...        # validate_plan
    def execute(self, plan) -> pd.DataFrame: ...                    # fetch_data(plan.url)
    def fingerprint(self, plan) -> dict: ...                        # parse_mrx_url(plan.url)
```

- `MultirowView` is the first implementation — it just *delegates* to the
  existing `generate_link` / `validation` / `data_fetch` functions. Their code
  barely moves; they get wrapped, not rewritten.
- A registry: `mrx/views/__init__.py: REGISTRY = {"multirow": MultirowView()}`.
  This is the "capability-as-data" layer — the MRX-appropriate version of
  LLM_CCR's skills idea, but a typed Python registry, not YAML + a loader
  (over-engineering for a handful of typed views).

## What threads the View through

- `fetch.get_view` / `fetch.plan_and_validate` take a `View` param (defaulting
  to the multirow view while it's the only one, so nothing upstream breaks).
- `fetch.find_reusable_dataset` / `router.find_reusable_dataset` /
  `router._covers` take the `View` so fingerprinting goes through
  `view.fingerprint(plan)` instead of hard-calling `parse_mrx_url`.
- `loop.run_agent_loop` gains an optional `view` (default multirow). *Which*
  view to use per question is a later concern (a second view doesn't exist
  yet) — the interface just has to make it a parameter now, not a hard import.

## What does NOT change

- The bounded loop, the `max_fetches` cap, the validation-gate discipline.
- `catalog` schema (`View` still yields `MRXPlan`).
- `smart_pandas` (already DataFrame-only).
- All 130 tests should stay green — this is a mechanical extraction: one view,
  same behavior, now reached through an interface instead of an import.

## Explicitly not built (named so it isn't assumed)

- No `Source` abstraction / non-MRX inputs (deferred — "maybe" future).
- No YAML skill files / skill loader / middleware (LLM_CCR's general-framework
  machinery; unjustified for typed MRX views).
- No LangGraph / create_agent (settled earlier — keeps our own hard cap).
- No per-question view *selection* logic yet (only one view exists; the
  interface makes selection possible, we wire it when a second view lands).

## Sequencing

Do this as a standalone, behavior-preserving refactor *before* a second view
exists — so the second view is an addition, not surgery. Verify by: all 130
tests green with multirow reached through the interface, plus one new test
that registers a trivial fake second View and confirms the loop can run it
end-to-end (proving the seam is real, not cosmetic).
```
