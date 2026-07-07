"""fetch_mrx — the MRX-expertise tool of the loop (the Task-subagent pattern).

Takes a NATURAL-LANGUAGE data request; inside: the nested URL-builder call
(the manuals/tables knowledge, never in the main context), the deterministic
validation gate with corrective retries, the HARD fetch budget, zero-cost
reuse, profiling, catalog persistence — the gated fetch primitive lives at
the bottom of this file.

Failures return as TEXT (not exceptions): the loop model reads the error and
corrects its request in the next iteration — in-loop self-correction, no
re-plan subsystem.
"""

from typing import Optional

import re
from datetime import datetime, timezone

from ...common.errors import BudgetExhausted, DataFetchError, PlanValidationError
from ...common.events import EventKind
from ...common.trace import Step
from ...mrx import generate_link, profiler, reuse
from ...storage import catalog
from ..session import Evidence

MAX_URL_ATTEMPTS = 3

TOOL_DESCRIPTION = (
    "Fetch data from MRX. Describe the data you need in natural language — "
    "measure, scope/node, breakdown (single dimension), time form (snapshot / "
    "compare with T-1 / history dates window), filters. The tool builds and "
    "validates the MRX URL itself, reuses already-fetched data at zero cost, "
    "and registers the returned dataframe in your python namespace. Returns "
    "the dataframe's label and its profile."
)


def fetch(session, url_llm, view, request: str) -> str:
    """Run the gated fetch for one NL request; returns the tool-result text."""
    attempts = []
    for _ in range(MAX_URL_ATTEMPTS):
        plan = generate_link.get_link(url_llm, request, prior_attempts=attempts)
        try:
            evidence = fetch_evidence(plan, view, session, query=request)
        except PlanValidationError as e:
            attempts.append((plan, str(e)))
            continue
        except BudgetExhausted as e:
            return (f"FETCH REFUSED — {e}. Do not request more data; answer "
                    f"from what is already in the namespace.")
        except DataFetchError as e:
            return (f"FETCH FAILED — {e}\nMRX URL: {getattr(e, 'url', '')}\n"
                    f"Correct the request (parameters/window/scope) or proceed "
                    f"without this data.")
        session.register_frame(evidence.label, evidence.df)
        return (f"registered as '{evidence.label}' ({evidence.provenance})\n"
                f"{evidence.profile.render_text()}\n"
                f"sample rows:\n{profiler.preview(evidence.df)}")
    last_error = attempts[-1][1] if attempts else "unknown validation error"
    return (f"FETCH FAILED — could not build a valid MRX view after "
            f"{MAX_URL_ATTEMPTS} attempts: {last_error}\nRephrase the request "
            f"(one breakdown dimension, a valid measure, explicit window).")


# ---- the gated fetch primitive (all gates live HERE, plain code) ----------



_LABEL_STOPWORDS = {
    "see", "the", "a", "an", "of", "on", "for", "from", "to", "with", "and",
    "vs", "versus", "between", "across", "columns", "dates", "date", "cob",
    "as", "at", "view", "show", "broken", "down", "by", "form", "current",
    "previous", "difference", "latest", "available", "daily",
}


def _unique_label(base: str, ctx) -> str:
    """A collision-free, CONCISE identifier for this evidence — the model
    retypes it in every run_python snippet, so intent prose ('See the daily
    history of...') is stripped to its content words and capped (a live audit
    found a 110-char label)."""
    tokens = re.sub(r"\W+", " ", (base or "data").strip().lower()).split()
    kept = [t for t in tokens if t not in _LABEL_STOPWORDS and not t.isdigit()]
    label = "_".join(kept) or "data"
    if len(label) > 48:
        label = label[:48].rsplit("_", 1)[0] or label[:48]
    if label[0].isdigit():
        label = f"d_{label}"
    taken = {e.label for e in ctx.evidence}
    candidate, n = label, 1
    while candidate in taken:
        n += 1
        candidate = f"{label}_{n}"
    return candidate


def _find_reusable(plan, view, ctx):
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


def fetch_evidence(plan, view, ctx, *, query: str) -> Evidence:
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
