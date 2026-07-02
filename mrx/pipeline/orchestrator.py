"""Ties the pipeline stages together: plan -> validate -> fetch -> answer.

Wired to the Multirow view today (imports generate_link/validation from
mrx.views.multirow directly below) — this module is the one place that
currently knows which view it's running. A genuinely multi-view future
would make that a per-question choice instead of a fixed import; not built
speculatively while there's only one view to route to.
"""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

import pandas as pd

from . import catalog
from . import data_fetch
from . import router
from . import smart_pandas
from .models import MRXPlan
from .pipeline_errors import AnswerError, PlanGenerationError, PlanValidationError
from .smart_pandas import AnswerResult
from ..views.multirow import generate_link
from ..views.multirow import validation

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


def _find_reusable_dataset(*, session_id: str, conversation_id: str, plan_url: str):
    """Look up a reusable dataset, degrading to "nothing found" on any
    catalog error (corrupt file, disk issue) rather than failing the whole
    pipeline — reuse is an optimization; its failure just means a normal
    fetch happens instead, same as a fresh-install/empty-catalog run.

    Deliberately re-queries the catalog fresh on every call rather than
    loading candidates once per pipeline run and sharing them across
    views: multi-fetch views now run CONCURRENTLY (see run() below), so a
    pre-loaded, shared snapshot would be stale the moment any other
    in-flight view finishes and catalogs its own fetch — freezing out
    exactly the kind of same-question, cross-view reuse ("two decomposed
    views turn out to need the same data") that a fresh per-call query can
    still catch. The extra query cost is small at this store's scale (see
    catalog.py's session/created_at index); the correctness of seeing
    concurrently-completing sibling views is worth more.
    """
    try:
        candidates = catalog.list_all(session_id=session_id, conversation_id=conversation_id)
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


def _save_to_catalog(*, session_id: str, conversation_id: str, query: str, plan: MRXPlan, df: pd.DataFrame) -> None:
    """Store this fetch in the durable catalog as a side effect.

    Never raises: `_find_reusable_dataset` reads this back on every
    subsequent fetch (see below), but a storage hiccup (disk full,
    permissions) here must still not prevent answering the CURRENT
    question — reuse for a future question is a nice-to-have, this
    question's answer is not. Uses `plan.intent` (already LLM-written
    during planning) as the dataset description rather than a new LLM
    call — cheap, and avoids adding latency/cost to every fetch.
    """
    try:
        dataset = catalog.Dataset(
            id=catalog.new_dataset_id(),
            session_id=session_id,
            conversation_id=conversation_id,
            query=query,
            plan=plan,
            created_at=datetime.now(timezone.utc).isoformat(),
            description=plan.intent,
            # schema omitted — catalog.save() derives it from `df`, which it
            # already has in scope, rather than this caller replicating the
            # same computation (and risking it drifting out of sync).
        )
        catalog.save(dataset, df)
    except Exception:
        pass


def _get_view(
    llm, view_query: str, *, session_id: str, conversation_id: str, min_confidence: float, max_attempts: int,
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

    reused = _find_reusable_dataset(session_id=session_id, conversation_id=conversation_id, plan_url=plan.url)
    df = _load_reused_df(reused.id) if reused else None
    if df is not None:
        if on_stage:
            on_stage("reuse" + stage_suffix)
    else:
        reused = None  # loading the reused dataset failed — fetch fresh instead
        if on_stage:
            on_stage("fetch" + stage_suffix)
        df = data_fetch.fetch_data(plan.url)
        _save_to_catalog(session_id=session_id, conversation_id=conversation_id, query=view_query, plan=plan, df=df)

    return ViewResult(
        query=view_query, plan=plan, df=df, attempts=attempts,
        reused_dataset_id=reused.id if reused else None,
    )


def _answer_from_context(context_datasets: list) -> list:
    """Build ViewResult entries directly from already-fetched conversation
    data, for the router's "answer_from_context" mode — no new plan or
    fetch, just load what's already on disk. Each dataset's ORIGINAL plan
    (from when it was fetched) is carried through unchanged, since there's
    no new plan to validate; `attempts=0` marks that no plan/validate loop
    ran for this view (distinguishing it from a genuinely single-attempt
    fresh fetch, which is `attempts=1`).

    Skips (rather than fails the whole question over) any dataset whose
    dataframe can't be loaded — same "degrade, don't crash" stance as
    `_load_reused_df` elsewhere in this module. If EVERY dataset fails to
    load, this returns an empty list — the caller (`run`, below) is
    responsible for turning that into an AnswerError rather than letting
    `views[0]` raise a raw IndexError. A load failure at this point means
    the pipeline is in a state (catalog metadata present, its parquet
    gone) it can't self-correct; surfacing a clean, caught PipelineError
    is the right degradation, not a silent empty answer or an unhandled
    crash.
    """
    views = []
    for dataset in context_datasets:
        df = _load_reused_df(dataset.id)
        if df is None:
            continue
        views.append(ViewResult(
            query=dataset.query, plan=dataset.plan, df=df, attempts=0,
            reused_dataset_id=dataset.id,
        ))
    return views


def run(
    llm,
    query: str,
    *,
    min_confidence: float = 0.7,
    max_attempts: int = 3,
    on_stage=None,
    on_token=None,
    session_id: Optional[str] = None,
    conversation_id: Optional[str] = None,
    allow_multi_fetch: bool = False,
) -> PipelineResult:
    """Run the full NL question -> MRX data -> answer pipeline.

    Every question needs at least one view: plan, reuse an already-fetched
    dataset if the catalog has one that covers it, or fetch fresh from MRX
    (see `_get_view`) — UNLESS the question can be answered purely from
    data already fetched earlier in this conversation, with no new MRX
    view at all (see `allow_multi_fetch` below). This is the whole pipeline
    unless `allow_multi_fetch` is set.

    `allow_multi_fetch`, if True, first asks `router.route()` how to answer
    this question:
    - "answer_from_context": a pure follow-up over data already fetched in
      this conversation (e.g. "what was the biggest daily variation") —
      skips planning and fetching entirely, loads the conversation's
      existing dataset(s) via `_answer_from_context`, and goes straight to
      the answer stage. Only offered when `conversation_id` is given AND
      the catalog already has data for it (see below) — router.route()
      isn't even given this option otherwise, so a first question in a
      conversation behaves exactly as before this mode existed.
    - "single_fetch"/"multi_fetch": one or several NEW MRX views are
      needed (e.g. "analyse the variation of FX Vega by desk, product, and
      deal" implies three) — unchanged from before this mode existed.

    Defaults to False (skipping the router call entirely): for the
    overwhelming majority of questions (a single lookup, no prior
    conversation), `route()` would just echo the query back as a single
    view — a redundant LLM round-trip ahead of the planning call that
    handles a plain query fine on its own. Callers expecting genuinely
    multi-view or conversational questions (the Streamlit UI) opt in
    explicitly; the CLI and simple/programmatic callers stay on the fast
    single-view path.

    On a rejected plan (PlanValidationError) or a plan-generation failure,
    the error is sent back to the LLM and the plan is retried up to
    `max_attempts` times before giving up. Fetch and answer stages are
    single-shot: their failures aren't the LLM's to fix by retrying.

    `on_stage`, if given, is called with a short stage name ("plan",
    "reuse", "fetch", "answer" for a single-view question; "plan:route",
    then per-view "plan:N", "reuse:N"/"fetch:N" for a multi-view one; just
    "plan:route" then "answer" for answer-from-context, since there's no
    plan/fetch stage to report) right before each stage starts — purely
    for UI progress feedback, it has no effect on the pipeline itself.

    `on_token`, if given, is passed through to the answer stage
    (smart_pandas.ask) to stream its code-generation and narration text as
    it's produced. The plan/route stages use structured output (parsed
    objects, not freeform prose), so there's no meaningful token stream to
    show for them — their progress stays a stage-status update via `on_stage`.

    `session_id`, if given, tags every fetch in the durable dataset catalog
    (see catalog.py). Defaults to a shared bucket when omitted (matches
    DEFAULT_SESSION_ID's catalog scoping).

    `conversation_id`, if given, is used (alongside `session_id`) to check
    whether a view can be answered from an already-fetched dataset instead
    of hitting MRX again — see `router.find_reusable_dataset` — and is what
    `allow_multi_fetch`'s "answer_from_context" mode looks up conversation
    data by. Unlike `session_id` (which resets on a page refresh),
    `conversation_id` is expected to be durable across a refresh/reopened
    conversation (see catalog.py's module docstring) — that durability is
    what lets a follow-up work again after reopening a saved conversation.
    When omitted, answer-from-context is never offered (there's no
    conversation to look data up for), same as `allow_multi_fetch=False`.

    Raises PlanGenerationError, PlanValidationError, DataFetchError, or
    AnswerError (all defined in pipeline_errors.py) if a stage fails or
    its output is unsafe to act on.
    """
    session_id = session_id or DEFAULT_SESSION_ID

    context_datasets = []
    if allow_multi_fetch and conversation_id:
        try:
            context_datasets = catalog.list_for_conversation(conversation_id=conversation_id)
        except Exception:
            context_datasets = []  # same "degrade, don't crash" stance as _find_reusable_dataset

    answering_from_context = False
    if allow_multi_fetch:
        if on_stage:
            on_stage("plan:route")
        decision = router.route(llm, query, context_datasets=context_datasets)
        if decision.mode == "answer_from_context":
            views = _answer_from_context(context_datasets)
            if not views:
                # Every context dataset's dataframe failed to load (catalog
                # metadata present, its parquet file gone) — this is not
                # recoverable by retrying, and MUST surface as a
                # PipelineError so app.py's `except PipelineError` catches
                # it cleanly instead of `views[0]` below raising a raw,
                # uncaught IndexError straight to the user.
                raise AnswerError(
                    "This conversation's earlier data could no longer be loaded "
                    "to answer this follow-up. Try asking the original question again."
                )
            multi = len(views) > 1
            answering_from_context = True
        else:
            view_queries = decision.new_view_queries or [query]
            multi = decision.mode == "multi_fetch" and len(view_queries) > 1
            views = None  # built below
    else:
        view_queries, multi, views = [query], False, None

    if views is None:
        if len(view_queries) == 1:
            views = [_get_view(
                llm, view_queries[0], session_id=session_id, conversation_id=conversation_id or DEFAULT_SESSION_ID,
                min_confidence=min_confidence, max_attempts=max_attempts,
                on_stage=on_stage, stage_suffix="",
            )]
        else:
            # Each view's plan+fetch is fully independent of the others (no
            # data dependency between "by desk" and "by product"), so running
            # them one after another paid roughly Nx the latency for no
            # benefit — a 3-view question waited for 3 sequential LLM calls
            # plus 3 sequential MRX round-trips. ThreadPoolExecutor.map
            # preserves input order in its output regardless of completion
            # order, so `views` still lines up with `view_queries` positionally.
            # Safe to run concurrently: catalog.py opens a fresh sqlite3
            # connection per call (never shared across threads), and on_stage
            # callbacks are individually distinguishable via stage_suffix even
            # if they now interleave from different threads.
            def _get_view_for(indexed_query):
                i, view_query = indexed_query
                return _get_view(
                    llm, view_query, session_id=session_id, conversation_id=conversation_id or DEFAULT_SESSION_ID,
                    min_confidence=min_confidence, max_attempts=max_attempts,
                    on_stage=on_stage, stage_suffix=f":{i}",
                )

            with ThreadPoolExecutor(max_workers=len(view_queries)) as pool:
                views = list(pool.map(_get_view_for, enumerate(view_queries, start=1)))

    if on_stage:
        on_stage("answer")

    primary = views[0]
    if len(views) == 1:
        # For a normal fetch/reuse, primary.plan.SmartDF is THIS question's
        # own LLM-rephrased form (see generate_link.get_link) — the right
        # primary question to answer. For answer_from_context, primary.plan
        # is the STORED dataset's ORIGINAL plan from when it was first
        # fetched — its SmartDF rephrases that old question, not this
        # follow-up. Using it here would silently re-answer the old
        # question instead of the new one, so answer_from_context passes
        # the actual current `query` as the primary question instead.
        question = query if answering_from_context else primary.plan.SmartDF
        answer = smart_pandas.ask(
            primary.df, question, llm, original_query=query, on_token=on_token
        )
    else:
        # A list of (label, df) pairs, NOT a dict — two views can have an
        # identical LLM-written `intent`, and building a dict here first
        # would silently drop one view's dataframe via key-overwrite before
        # sanitize_names ever gets a chance to disambiguate them.
        labeled = [(v.plan.intent or v.query, v.df) for v in views]
        named_datasets = smart_pandas.sanitize_names(labeled)
        answer = smart_pandas.ask(named_datasets, query, llm, on_token=on_token)

    return PipelineResult(
        plan=primary.plan, df=primary.df, answer=answer, attempts=primary.attempts,
        reused_dataset_id=primary.reused_dataset_id,
        views=views if multi else None,
    )
