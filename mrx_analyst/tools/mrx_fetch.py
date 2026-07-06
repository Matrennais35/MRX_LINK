"""The validated fetch step — the ONLY way data enters a run.

For one FetchSpec-resolved MRXPlan: deterministic reuse-check (a cataloged
dataset covering the same params costs ZERO budget) → the validation gate
(never bypassed, model-independent) → budget.acquire() (hard cap, plain code)
→ execute via the view → profile → catalog save → Evidence.

This is the orchestrator's fetch primitive, not an agent-proposed Tool: agents
propose WHAT to fetch (DataScout's specs); this code decides whether it's
allowed to happen and records everything about it.
"""

import re
from datetime import datetime, timezone
from typing import Optional

from ..core.context import Evidence, RunContext
from ..core.errors import DataFetchError
from ..core.events import EventKind
from ..core.models import MRXPlan
from ..core.trace import Step
from ..storage import catalog
from ..views import reuse
from . import profiler


def _unique_label(base: str, ctx: RunContext) -> str:
    """A collision-free identifier for this evidence (tool args and codegen
    refer to datasets by label)."""
    label = re.sub(r"\W+", "_", (base or "data").strip().lower()).strip("_") or "data"
    if label[0].isdigit():
        label = f"d_{label}"
    taken = {e.label for e in ctx.evidence}
    candidate, n = label, 1
    while candidate in taken:
        n += 1
        candidate = f"{label}_{n}"
    return candidate


def _find_reusable(plan: MRXPlan, view, ctx: RunContext):
    """A cataloged dataset whose stored params cover this plan, or None.
    Degrades to None on any catalog error — reuse is an optimization; its
    failure just means a normal (budgeted, gated) fetch happens."""
    try:
        candidates = catalog.list_all(
            session_id=ctx.session_id,
            conversation_id=ctx.conversation_id,
        )
        return reuse.find_reusable_dataset(candidates, plan, fingerprint=view.fingerprint)
    except Exception:
        return None


def fetch_evidence(plan: MRXPlan, view, ctx: RunContext, *, query: str) -> Evidence:
    """Run the full gated fetch pipeline for one plan. Raises
    PlanValidationError (gate), BudgetExhausted (cap), or DataFetchError
    (MRX failure, carrying the URL) — the orchestrator decides what each
    means for the run.
    """
    # 1. Reuse first — costs no budget, no MRX call.
    reused = _find_reusable(plan, view, ctx)
    if reused is not None:
        # Already in this run's evidence (e.g. wave 2 re-designing a wave-1
        # view)? Return the existing entry — don't append a duplicate that
        # would pollute the Analyst's context with _2-suffixed copies.
        for existing in ctx.evidence:
            if existing.dataset_id == reused.id:
                ctx.trace.append(Step(kind="gate", name="reuse",
                                      summary=f"already loaded: {existing.label}",
                                      detail={"dataset_id": reused.id}))
                ctx.emit(EventKind.FETCH, {"stage": "reused", "label": existing.label})
                return existing
        try:
            df = catalog.load_df(reused.id)
        except Exception:
            df = None
        if df is not None:
            prof = profiler.profile(df)
            evidence = Evidence(
                dataset_id=reused.id, label=_unique_label(plan.intent, ctx),
                plan=reused.plan, df=df, profile=prof, provenance="reused",
            )
            ctx.evidence.append(evidence)
            ctx.trace.append(Step(kind="gate", name="reuse",
                                  summary=f"reused cached data for: {plan.intent}",
                                  detail={"dataset_id": reused.id}))
            ctx.emit(EventKind.FETCH, {"stage": "reused", "label": evidence.label})
            return evidence

    # 2. The validation gate — model-independent, never bypassed.
    view.validate(plan)

    # 3. The hard budget — plain code; BudgetExhausted propagates to the
    # orchestrator, which stops the fetch phase and proceeds with what it has.
    ctx.budget.acquire()

    # 4. Execute + profile + persist.
    ctx.emit(EventKind.FETCH, {"stage": "fetching", "label": plan.intent, "url": plan.url})
    df = view.execute(plan)
    # MRX signals a bad request as a SUCCESSFUL response whose only content is
    # an 'Invalid Parameters' column (a real eval failure: two such frames
    # entered evidence and burned budget). Treat it as the fetch failure it is
    # — the error feeds the scout's corrective re-plan, with the URL to fix.
    if any("invalid parameter" in str(c).lower() for c in df.columns):
        raise DataFetchError(
            "MRX returned 'Invalid Parameters' for this view — the URL's "
            "parameters are wrong (check mandatory params and code values).",
            url=plan.url,
        )
    prof = profiler.profile(df)

    dataset_id = catalog.new_dataset_id()
    try:
        catalog.save(catalog.Dataset(
            id=dataset_id, session_id=ctx.session_id,
            conversation_id=ctx.conversation_id or ctx.session_id,
            query=query, plan=plan,
            created_at=datetime.now(timezone.utc).isoformat(),
            description=plan.intent,
        ), df)
    except Exception:
        pass  # storage hiccup must not lose the fetched answer-in-progress

    evidence = Evidence(
        dataset_id=dataset_id, label=_unique_label(plan.intent, ctx),
        plan=plan, df=df, profile=prof, provenance="fetched",
    )
    ctx.evidence.append(evidence)
    ctx.trace.append(Step(kind="gate", name="fetch",
                          summary=f"fetched: {plan.intent} ({df.shape[0]}x{df.shape[1]})",
                          detail={"dataset_id": dataset_id, "url": plan.url,
                                  "budget_used": ctx.budget.used}))
    ctx.emit(EventKind.FETCH, {"stage": "done", "label": evidence.label})
    return evidence
