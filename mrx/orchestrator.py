"""Ties the pipeline stages together: plan -> validate -> fetch -> answer."""

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

import pandas as pd

from . import catalog
from . import data_fetch
from . import generate_link
from . import router
from . import smart_pandas
from . import validation
from .generate_link import MRXPlan
from .pipeline_errors import PlanGenerationError, PlanValidationError
from .smart_pandas import AnswerResult

# Used when a caller doesn't care about catalog scoping (CLI, most existing
# tests) — keeps every fetch attributable to *some* session rather than an
# empty/None value the catalog schema doesn't expect.
DEFAULT_SESSION_ID = "default"


@dataclass
class ViewResult:
    """One fetched-or-reused view within a multi-view question. `plan` and
    `attempts` describe how this specific view was obtained; `reused_dataset_id`
    is set when this view was answered from the catalog instead of a fresh fetch.
    """
    query: str
    plan: MRXPlan
    df: pd.DataFrame
    attempts: int
    reused_dataset_id: Optional[str] = None


@dataclass
class PipelineResult:
    plan: MRXPlan
    df: pd.DataFrame
    answer: AnswerResult
    attempts: int
    reused_dataset_id: Optional[str] = None
    views: Optional[list] = None


def _plan_and_validate(llm, query: str, *, min_confidence: float, max_attempts: int) -> tuple[MRXPlan, int]:
    """Build and validate a plan, feeding validation errors back to the LLM
    to self-correct, up to `max_attempts` tries. Raises the last error if
    every attempt is exhausted.
    """
    prior_attempts: list[tuple[MRXPlan, str]] = []

    for attempt in range(1, max_attempts + 1):
        try:
            plan = generate_link.get_link(llm, query, prior_attempts=prior_attempts)
        except Exception as e:
            if attempt == max_attempts:
                raise PlanGenerationError(f"Failed to build an MRX plan: {e}") from e
            continue

        try:
            validation.validate_plan(plan, min_confidence=min_confidence)
        except PlanValidationError as e:
            if attempt == max_attempts:
                raise
            prior_attempts.append((plan, str(e)))
            continue

        return plan, attempt

    # Unreachable: the loop always either returns or raises on the last attempt.
    raise AssertionError("plan/validate loop exited without returning or raising")


def _find_reusable_dataset(*, session_id: str, plan_url: str):
    """Look up a reusable dataset, degrading to "nothing found" on any
    catalog error (corrupt file, disk issue) rather than failing the whole
    pipeline — reuse is an optimization; its failure just means a normal
    fetch happens instead, same as a fresh-install/empty-catalog run.
    """
    try:
        candidates = catalog.list_all(session_id=session_id)
        return router.find_reusable_dataset(candidates, plan_url)
    except Exception:
        return None


def _load_reused_df(dataset_id: str):
    """Load a reused dataset's dataframe, or None if that fails — falls
    back to a fresh fetch rather than raising, for the same reason as
    `_find_reusable_dataset`.
    """
    try:
        return catalog.load_df(dataset_id)
    except Exception:
        return None


def _save_to_catalog(*, session_id: str, query: str, plan: MRXPlan, df: pd.DataFrame) -> None:
    """Store this fetch in the durable catalog as a side effect.

    Never raises: cataloging is a phase-1 feature with no consumer yet (no
    reuse logic reads it back), so a storage hiccup (disk full, permissions)
    must not prevent answering the user's actual question. Uses `plan.intent`
    (already LLM-written during planning) as the dataset description rather
    than a new LLM call — cheap, and avoids adding latency/cost to every
    fetch for a feature nothing consumes yet.
    """
    try:
        dataset = catalog.Dataset(
            id=catalog.new_dataset_id(),
            session_id=session_id,
            query=query,
            plan=plan,
            created_at=datetime.now(timezone.utc).isoformat(),
            description=plan.intent,
            schema={col: str(dtype) for col, dtype in df.dtypes.items()},
        )
        catalog.save(dataset, df)
    except Exception:
        pass


def _get_view(
    llm, view_query: str, *, session_id: str, min_confidence: float, max_attempts: int,
    on_stage=None, stage_suffix: str = "",
) -> ViewResult:
    """Obtain one view's data — the single-view logic every question used
    to run directly, now also the building block multi-fetch loops over
    once per decomposed view query. Always plans first (cheap), then
    checks the catalog for a deterministic reuse match before fetching.

    `stage_suffix`, if given, is appended to "fetch"/"reuse" stage names
    (e.g. "fetch:by-desk") so a multi-fetch question's per-view progress is
    distinguishable in the UI — see app.py's `_stage_label` fallback for
    stage names outside the fixed plan/reuse/fetch/answer set.
    """
    if on_stage:
        on_stage("plan" + stage_suffix)
    plan, attempts = _plan_and_validate(
        llm, view_query, min_confidence=min_confidence, max_attempts=max_attempts
    )

    reused = _find_reusable_dataset(session_id=session_id, plan_url=plan.url)
    df = _load_reused_df(reused.id) if reused else None
    if df is not None:
        if on_stage:
            on_stage("reuse" + stage_suffix)
    else:
        reused = None  # loading the reused dataset failed — fetch fresh instead
        if on_stage:
            on_stage("fetch" + stage_suffix)
        df = data_fetch.fetch_data(plan.url)
        _save_to_catalog(session_id=session_id, query=view_query, plan=plan, df=df)

    return ViewResult(
        query=view_query, plan=plan, df=df, attempts=attempts,
        reused_dataset_id=reused.id if reused else None,
    )


def run(
    llm,
    query: str,
    *,
    min_confidence: float = 0.7,
    max_attempts: int = 3,
    on_stage=None,
    on_token=None,
    session_id: Optional[str] = None,
    allow_multi_fetch: bool = False,
) -> PipelineResult:
    """Run the full NL question -> MRX data -> answer pipeline.

    Every question needs at least one view: plan, reuse an already-fetched
    dataset if the catalog has one that covers it, or fetch fresh from MRX
    (see `_get_view`). This is the whole pipeline unless `allow_multi_fetch`
    is set.

    `allow_multi_fetch`, if True, first asks `router.route()` whether this
    question needs one view or several (e.g. "analyse the variation of FX
    Vega by desk, product, and deal" implies three). Defaults to False: for
    the overwhelming majority of questions (a single lookup), `route()`
    would just echo the query back as a single view — a redundant LLM
    round-trip ahead of the planning call that handles a plain query fine
    on its own. Callers expecting genuinely multi-view questions (the
    Streamlit UI) opt in explicitly; the CLI and simple/programmatic
    callers stay on the fast single-view path.

    On a rejected plan (PlanValidationError) or a plan-generation failure,
    the error is sent back to the LLM and the plan is retried up to
    `max_attempts` times before giving up. Fetch and answer stages are
    single-shot: their failures aren't the LLM's to fix by retrying.

    `on_stage`, if given, is called with a short stage name ("plan",
    "reuse", "fetch", "answer" for a single-view question; "plan:route",
    then per-view "plan:N", "reuse:N"/"fetch:N" for a multi-view one)
    right before each stage starts — purely for UI progress feedback, it
    has no effect on the pipeline itself.

    `on_token`, if given, is passed through to the answer stage
    (smart_pandas.ask) to stream its code-generation and narration text as
    it's produced. The plan/route stages use structured output (parsed
    objects, not freeform prose), so there's no meaningful token stream to
    show for them — their progress stays a stage-status update via `on_stage`.

    `session_id`, if given, tags every fetch in the durable dataset catalog
    (see catalog.py), and is used to check whether a view can be answered
    from an already-fetched dataset instead of hitting MRX again — see
    `router.find_reusable_dataset`. Defaults to a shared bucket when
    omitted (matches DEFAULT_SESSION_ID's catalog scoping).

    Raises PlanGenerationError, PlanValidationError, DataFetchError, or
    AnswerError (all defined in pipeline_errors.py) if a stage fails or
    its output is unsafe to act on.
    """
    session_id = session_id or DEFAULT_SESSION_ID

    if allow_multi_fetch:
        if on_stage:
            on_stage("plan:route")
        decision = router.route(llm, query)
        view_queries = decision.new_view_queries or [query]
        multi = decision.mode == "multi_fetch" and len(view_queries) > 1
    else:
        view_queries, multi = [query], False

    views = []
    for i, view_query in enumerate(view_queries, start=1):
        suffix = f":{i}" if multi else ""
        views.append(_get_view(
            llm, view_query, session_id=session_id,
            min_confidence=min_confidence, max_attempts=max_attempts,
            on_stage=on_stage, stage_suffix=suffix,
        ))

    if on_stage:
        on_stage("answer")

    primary = views[0]
    if len(views) == 1:
        answer = smart_pandas.ask(
            primary.df, primary.plan.SmartDF, llm, original_query=query, on_token=on_token
        )
    else:
        labeled = {v.plan.intent or v.query: v.df for v in views}
        named_datasets = smart_pandas.sanitize_names(labeled)
        answer = smart_pandas.ask(named_datasets, query, llm, on_token=on_token)

    return PipelineResult(
        plan=primary.plan, df=primary.df, answer=answer, attempts=primary.attempts,
        reused_dataset_id=primary.reused_dataset_id,
        views=views if multi else None,
    )
