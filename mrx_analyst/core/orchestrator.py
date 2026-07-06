"""The orchestrator — the whole run in plain code.

Flow (see the approved rebuild plan): load context → Planner → (respond
short-circuit) → DataScout wave 1 → gated parallel fetches → optional wave-2
drill (a second DataScout call fed the wave-1 profiles) → Analyst (toolkit ops,
codegen fallback) → Narrator synthesis → Critic (anchored; ONE refine) →
persist turn + trace + chart.

Every loop, retry counter, budget check, and gate lives HERE — agents propose,
this code disposes. That's the auditability contract: the model never holds
control flow over a production risk system.
"""

import io
import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import List, Optional

from pydantic import ValidationError

from ..agents import narrator
from ..agents.analyst import Analyst, AnalysisSpec, Facts
from ..agents.critic import Critic
from ..agents.datascout import DataScout
from ..agents.planner import Planner
from ..storage import catalog
from ..tools import codegen, mrx_fetch, profiler
from ..tools.analysis.toolkit import TOOLKIT
from ..views import DEFAULT_VIEW
from .answer import Answer
from .context import Evidence, FetchBudget, RunContext
from .errors import AnswerError, BudgetExhausted, DataFetchError, PipelineError, PlanValidationError
from .events import EventKind, no_emit
from .tool import run_tool
from .trace import Step

# Retry counters — plain code, never prompt-enforced.
MAX_SCOUT_REPLANS = 1     # one corrective DataScout re-plan after fetch/gate failures
MAX_ANALYST_RETRIES = 1   # one corrected Analyst proposal after a failed op
MAX_REFINES = 1           # one Critic-driven refine pass, then ship


@dataclass
class TurnResult:
    answer: Answer
    turn_id: str
    ctx: RunContext           # carries plan, evidence, trace for rendering/debug


def run_turn(
    llm,
    query: str,
    *,
    session_id: str,
    conversation_id: Optional[str] = None,
    emit=no_emit,
    max_fetches: Optional[int] = None,
    view=None,
) -> TurnResult:
    """Answer one question end-to-end. Raises PipelineError subclasses on
    unrecoverable failures (each already traced and emitted)."""
    view = view if view is not None else DEFAULT_VIEW  # resolved at call time (testable)
    ctx = RunContext(query=query, session_id=session_id, conversation_id=conversation_id,
                     turn_id=catalog.new_turn_id(), emit=emit)
    if max_fetches is not None:
        ctx.budget = FetchBudget(max_fetches=max_fetches)

    _load_context(ctx)

    # ---- PLAN ---------------------------------------------------------------
    ctx.emit(EventKind.STATUS, {"label": "Planning the analysis…"})
    ctx.plan = Planner().run(llm, ctx)

    if not ctx.plan.needs_data:
        # Respond short-circuit: no fetch machinery at all (2 LLM calls total).
        ctx.emit(EventKind.STATUS, {"label": "Answering…"})
        narrative = narrator.respond(llm, ctx)
        answer = Answer(narrative=narrative)
        _persist(ctx, answer)
        return TurnResult(answer=answer, turn_id=ctx.turn_id, ctx=ctx)

    # ---- FETCH (two waves, all gates in code) --------------------------------
    scout = DataScout()
    ctx.emit(EventKind.STATUS, {"label": "Designing the MRX views…"})
    fetch_plan = scout.run(llm, ctx)
    _run_fetch_wave(llm, scout, fetch_plan.specs, ctx, view, parallel=True)

    if fetch_plan.drill_after_overview and ctx.budget.used < ctx.budget.max_fetches:
        # Wave 2 — the adaptive drill: the scout now sees the wave-1 profiles.
        ctx.emit(EventKind.STATUS, {"label": "Designing the drill-down…"})
        drill_plan = scout.run(llm, ctx)
        _run_fetch_wave(llm, scout, drill_plan.specs, ctx, view, parallel=False)

    if not ctx.evidence:
        raise AnswerError(
            "No data could be fetched to answer this question — every planned "
            "view failed or was refused. See the trace for the specific errors."
        )

    # ---- ANALYZE (toolkit first, codegen fallback) ---------------------------
    ctx.emit(EventKind.STATUS, {"label": "Computing…"})
    facts = _compute_facts(llm, ctx)

    # ---- NARRATE -------------------------------------------------------------
    ctx.emit(EventKind.STATUS, {"label": "Writing the analysis…"})
    narrative = narrator.synthesize(llm, ctx, facts)

    # ---- CRITIQUE (anchored, ONE refine) --------------------------------------
    critique = Critic(facts=facts, narrative=narrative).run(llm, ctx)
    if critique.verdict == "revise" and critique.issues:
        numeric = [i.detail for i in critique.issues if i.kind == "numeric"]
        narrative_issues = [i.detail for i in critique.issues if i.kind != "numeric"]
        if numeric:
            ctx._analyst_error = "the checker found numeric problems: " + "; ".join(numeric)
            ctx.emit(EventKind.STATUS, {"label": "Re-computing (checker found numeric issues)…"})
            try:
                facts = _compute_facts(llm, ctx)
            except PipelineError:
                pass  # keep the original facts — one refine, never a loop
        ctx.emit(EventKind.STATUS, {"label": "Revising the analysis…"})
        narrative = narrator.synthesize(
            llm, ctx, facts, refine_guidance="; ".join(numeric + narrative_issues)
        )
        # Ship unconditionally now — the refine cap is code, not judgment.

    answer = Answer(
        narrative=narrative,
        table=facts.table,
        chart=facts.chart,
        value=_single_metric(facts),
    )
    _persist(ctx, answer, facts=facts)
    return TurnResult(answer=answer, turn_id=ctx.turn_id, ctx=ctx)


# ---- stages ------------------------------------------------------------------

def _load_context(ctx: RunContext) -> None:
    """Prior turns + this conversation's datasets (profiled) as zero-cost
    evidence, so follow-ups plan against what already exists. Degrades to
    empty on any storage error."""
    if not ctx.conversation_id:
        return
    try:
        ctx.history = catalog.list_turns(conversation_id=ctx.conversation_id)
    except Exception:
        ctx.history = []
    try:
        for dataset in catalog.list_for_conversation(conversation_id=ctx.conversation_id):
            df = None
            try:
                df = catalog.load_df(dataset.id)
            except Exception:
                pass
            if df is None:
                continue
            ctx.evidence.append(Evidence(
                dataset_id=dataset.id,
                label=mrx_fetch._unique_label(dataset.description, ctx),
                plan=dataset.plan, df=df, profile=profiler.profile(df),
                provenance="reused",
            ))
    except Exception:
        pass


def _run_fetch_wave(llm, scout, specs, ctx: RunContext, view, *, parallel: bool) -> None:
    """Execute one wave of FetchSpecs through the gated fetch. Independent
    wave-1 specs run in a thread pool (budget acquire is locked); failures are
    collected and, once per turn, handed back to the scout for ONE corrective
    re-plan. BudgetExhausted stops the wave and is recorded — the run proceeds
    with the evidence it has.
    """
    errors = _fetch_specs(specs, ctx, view, parallel=parallel)

    replans = 0
    while errors and replans < MAX_SCOUT_REPLANS:
        replans += 1
        ctx._scout_errors = "\n".join(errors)  # surfaced via the scout's prompt
        ctx.emit(EventKind.STATUS, {"label": "Re-planning failed fetches…"})
        try:
            retry_plan = scout.run(llm, ctx)
        except Exception:
            break
        errors = _fetch_specs(retry_plan.specs, ctx, view, parallel=False)


def _fetch_specs(specs, ctx: RunContext, view, *, parallel: bool) -> List[str]:
    """Run specs through fetch_evidence, returning collected error strings.
    BudgetExhausted is terminal for the wave (recorded as a gate step)."""
    errors: List[str] = []

    def one(spec):
        try:
            mrx_fetch.fetch_evidence(spec.mrx_plan, view, ctx, query=ctx.query)
        except BudgetExhausted as e:
            ctx.trace.append(Step(kind="gate", name="budget", status="refused",
                                  summary=str(e), detail={"spec": spec.justification}))
            ctx.emit(EventKind.STATUS, {"label": "Fetch budget reached — proceeding with gathered data"})
        except (PlanValidationError, DataFetchError) as e:
            url = getattr(e, "url", None)
            ctx.trace.append(Step(kind="gate", name="fetch_failed", status="failed",
                                  summary=str(e), detail={"url": url or spec.mrx_plan.url}))
            ctx.emit(EventKind.ERROR, {"message": str(e), "url": url or spec.mrx_plan.url})
            errors.append(f"{spec.justification}: {e}")

    if parallel and len(specs) > 1:
        with ThreadPoolExecutor(max_workers=len(specs)) as pool:
            list(pool.map(one, specs))
    else:
        for spec in specs:
            one(spec)
    return errors


def _compute_facts(llm, ctx: RunContext) -> Facts:
    """The Analyst proposes; this code executes — toolkit ops with ONE
    corrected re-proposal, then the codegen fallback."""
    analyst = Analyst()
    spec = analyst.run(llm, ctx)

    attempts = 0
    while True:
        try:
            return _execute_spec(llm, spec, ctx)
        except (ValueError, ValidationError) as e:
            attempts += 1
            if attempts > MAX_ANALYST_RETRIES:
                # Last resort: free-form codegen over the raw frames.
                request = spec.fallback_code_request or ctx.query
                return _codegen_facts(llm, ctx, request)
            ctx._analyst_error = str(e)
            spec = analyst.run(llm, ctx)


def _execute_spec(llm, spec: AnalysisSpec, ctx: RunContext) -> Facts:
    """Execute an AnalysisSpec's toolkit calls in order. The first table-
    producing op becomes Facts.table and is registered as evidence 'facts' so
    chart ops can reference it. A declared fallback_code_request with no ops
    goes straight to codegen."""
    if not spec.ops:
        request = spec.fallback_code_request or ctx.query
        return _codegen_facts(llm, ctx, request)

    facts = Facts()
    by_name = {t.name: t for t in TOOLKIT}
    for call in spec.ops:
        tool = by_name.get(call.tool)
        if tool is None:
            raise ValueError(f"unknown toolkit tool {call.tool!r} — available: {sorted(by_name)}")
        try:
            raw_args = json.loads(call.args_json or "{}")
        except json.JSONDecodeError as e:
            raise ValueError(f"args_json for {call.tool} is not valid JSON: {e}")
        args = tool.Args(**raw_args)    # ValidationError -> corrected re-proposal
        result = run_tool(tool, args, ctx)
        facts.ops_summary.append(result.summary)
        value = result.value
        if hasattr(value, "shape") and hasattr(value, "columns"):      # DataFrame
            if facts.table is None:
                facts.table = value
                _register_facts_evidence(value, ctx)
        elif hasattr(value, "savefig"):                                 # Figure
            facts.chart = value
        elif isinstance(value, dict):
            facts.metrics.update({k: v for k, v in value.items()
                                  if isinstance(v, (int, float, str))})
            inner = value.get("table")
            if facts.table is None and inner is not None:
                facts.table = inner
                _register_facts_evidence(inner, ctx)
    return facts


def _register_facts_evidence(table, ctx: RunContext) -> None:
    """Expose the computed table as evidence label 'facts' for chart ops."""
    ctx.evidence = [e for e in ctx.evidence if e.label != "facts"]
    ctx.evidence.append(Evidence(
        dataset_id="facts", label="facts", plan=None, df=table,
        profile=profiler.profile(table), provenance="computed",
    ))


def _codegen_facts(llm, ctx: RunContext, request: str) -> Facts:
    """The free-form fallback: generate + sandbox-run pandas over the raw
    frames, mapped into Facts. Raises AnswerError when even this fails."""
    datasets = {e.label: e.df for e in ctx.evidence if e.label != "facts"}
    try:
        result = codegen.generate_and_run(llm, datasets, request)
    except ValueError as e:
        raise AnswerError(f"could not compute an answer over the data: {e}")
    ctx.trace.append(Step(kind="tool", name="codegen",
                          summary=f"fallback code computed a {result.get('type')}",
                          detail={"request": request, "code": result.get("code", "")}))
    facts = Facts(code=result.get("code", ""), ops_summary=["codegen fallback"])
    rtype, value = result.get("type"), result.get("value")
    if rtype == "dataframe":
        facts.table = value
    elif rtype == "chart":
        facts.chart = value
    elif rtype == "composed":
        facts.table, facts.chart = value.get("table"), value.get("chart")
    else:
        facts.metrics["result"] = value
    return facts


def _single_metric(facts: Facts) -> Optional[str]:
    if len(facts.metrics) == 1:
        return str(next(iter(facts.metrics.values())))
    return None


def _persist(ctx: RunContext, answer: Answer, facts: Optional[Facts] = None) -> None:
    """Turn + trace + chart PNG. Best-effort: a storage hiccup must never take
    away an answer the user already has."""
    try:
        catalog.save_turn(catalog.Turn(
            id=ctx.turn_id,
            conversation_id=ctx.conversation_id or ctx.session_id,
            created_at=datetime.now(timezone.utc).isoformat(),
            question=ctx.query,
            narration=answer.narrative,
            method="; ".join(facts.ops_summary) if facts else "",
            answer_type="answer",
            value_preview=_preview(answer),
            code=facts.code if facts else "",
        ))
        catalog.save_steps(ctx.trace, turn_id=ctx.turn_id,
                           conversation_id=ctx.conversation_id or ctx.session_id)
        if answer.chart is not None:
            buf = io.BytesIO()
            answer.chart.savefig(buf, format="png", bbox_inches="tight", dpi=110)
            catalog.save_turn_image(ctx.turn_id, buf.getvalue())
    except Exception:
        pass


def _preview(answer: Answer) -> str:
    parts = []
    if answer.value is not None:
        parts.append(answer.value)
    if answer.table is not None:
        parts.append(f"table {answer.table.shape[0]}x{answer.table.shape[1]}")
    if answer.chart is not None:
        parts.append("chart")
    return " + ".join(parts) or "prose"
