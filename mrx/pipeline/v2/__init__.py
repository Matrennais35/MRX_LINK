"""MRX V2 — a bounded controller loop layered on the existing V1 pipeline.

This package is the *only* new orchestration. It deliberately does NOT copy
V1's primitives — it imports and reuses them (`orchestrator._get_view`,
`validation.validate_plan`, `catalog`, `smart_pandas.ask`) so the validation
gate that protects the production risk system has exactly one implementation,
never two that can drift. See docs/agent_loop_design.md for the full design
and the reasoning behind Option A (reuse, not fork).

What's new here (and nowhere else):
- `step.StepDecision` / `decide_next_step` — the per-iteration LLM call that
  replaces V1's single up-front `router.route()` classification.
- `loop.run_agent_loop` — the bounded fetch→observe→decide loop itself.
- catalog step-trace persistence (the "why each fetch happened" audit chain).
"""
