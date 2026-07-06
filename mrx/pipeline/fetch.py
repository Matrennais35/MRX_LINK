"""View-fetch primitives: obtain one view's data as plan -> validate ->
reuse-or-fetch -> catalog-save.

This is the single, validation-gated fetch path the whole pipeline runs
through — the controller loop (mrx/pipeline/loop.py) calls `get_view`
once per step, so there is exactly one place that plans, validates, reuse-
checks and stores an MRX fetch. Extracted into its own module so the fetch
primitives have a home separate from the loop that drives them.

View-agnostic: which MRX view is used comes in as a `View` argument (see
mrx/views/base.py), defaulting to the registered default view. This module no
longer hard-imports a specific view — planning, validation, execution and
reuse-fingerprinting all go through the passed-in view, so a second view is
"pass a different View" with no change here. See docs/view_interface_design.md.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

import pandas as pd

from . import catalog
from . import router
from .models import MRXPlan
from .pipeline_errors import PlanGenerationError, PlanValidationError
from ..views import DEFAULT_VIEW
from ..views.base import View

# Used when a caller doesn't care about catalog scoping (CLI, most existing
# tests) — keeps every fetch attributable to *some* session rather than an
# empty/None value the catalog schema doesn't expect.
DEFAULT_SESSION_ID = "default"


@dataclass
class ViewResult:
    """One fetched-or-reused view. `plan` and `attempts` describe how this
    specific view was obtained; `reused_dataset_id` is set when this view was
    answered from the catalog instead of a fresh fetch.
    """
    query: str
    plan: MRXPlan
    df: pd.DataFrame
    attempts: int
    reused_dataset_id: Optional[str] = None


def plan_and_validate(llm, query: str, *, view: View, min_confidence: float, max_attempts: int) -> tuple[MRXPlan, int]:
    """Build and validate a plan for `view`, feeding validation errors back to
    the LLM to self-correct, up to `max_attempts` tries. Raises the last error
    if every attempt is exhausted.
    """
    prior_attempts: list[tuple[MRXPlan, str]] = []

    for attempt in range(1, max_attempts + 1):
        try:
            plan = view.plan(llm, query, prior_attempts=prior_attempts)
        except Exception as e:
            if attempt == max_attempts:
                raise PlanGenerationError(f"Failed to build an MRX plan: {e}") from e
            continue

        try:
            view.validate(plan, min_confidence=min_confidence)
        except PlanValidationError as e:
            if attempt == max_attempts:
                raise
            prior_attempts.append((plan, str(e)))
            continue

        return plan, attempt

    # Unreachable: the loop always either returns or raises on the last attempt.
    raise AssertionError("plan/validate loop exited without returning or raising")


def find_reusable_dataset(*, view: View, session_id: str, conversation_id: str, plan: MRXPlan):
    """Look up a reusable dataset for `plan`, degrading to "nothing found" on
    any catalog error (corrupt file, disk issue) rather than failing the whole
    pipeline — reuse is an optimization; its failure just means a normal
    fetch happens instead, same as a fresh-install/empty-catalog run.

    Reuse-matching is fingerprinted by the view (`view.fingerprint`), so the
    router never hard-calls a specific view's URL parser. NOTE: with one view,
    every stored dataset and the fresh plan share that view, so one fingerprint
    function is correct. A multi-view future where a stored dataset came from a
    *different* view than `view` would need per-dataset fingerprinting — called
    out here so it isn't assumed away.

    Deliberately re-queries the catalog fresh on every call rather than
    loading candidates once: the controller loop's fetches are sequential, but
    a fresh per-call query still catches same-conversation reuse the moment a
    prior step catalogs its own fetch.
    """
    try:
        candidates = catalog.list_all(session_id=session_id, conversation_id=conversation_id)
        return router.find_reusable_dataset(candidates, plan, fingerprint=view.fingerprint)
    except Exception:
        return None


def load_reused_df(dataset_id: str):
    """Load a reused dataset's dataframe, or None if that fails — falls
    back to a fresh fetch rather than raising, for the same reason as
    `find_reusable_dataset`.
    """
    try:
        return catalog.load_df(dataset_id)
    except Exception:
        return None


def save_to_catalog(*, session_id: str, conversation_id: str, query: str, plan: MRXPlan, df: pd.DataFrame) -> None:
    """Store this fetch in the durable catalog as a side effect.

    Never raises: `find_reusable_dataset` reads this back on every
    subsequent fetch, but a storage hiccup (disk full, permissions) here
    must still not prevent answering the CURRENT question. Uses `plan.intent`
    (already LLM-written during planning) as the dataset description rather
    than a new LLM call — cheap, and avoids adding latency/cost to every fetch.
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
            # schema omitted — catalog.save() derives it from `df`.
        )
        catalog.save(dataset, df)
    except Exception:
        pass


def get_view(
    llm, view_query: str, *, view: View = DEFAULT_VIEW, session_id: str, conversation_id: str,
    min_confidence: float, max_attempts: int, on_stage=None, stage_suffix: str = "",
) -> ViewResult:
    """Obtain one view's data — plan first (cheap), then check the catalog for
    a deterministic reuse match before fetching. The controller loop calls
    this once per step.

    `view` selects which MRX view to plan/validate/execute/fingerprint
    against; defaults to the registered default view (the only one today).

    `stage_suffix`, if given, is appended to "fetch"/"reuse" stage names
    (e.g. "fetch:2") so per-step progress is distinguishable in the UI.
    """
    if on_stage:
        on_stage("plan" + stage_suffix)
    plan, attempts = plan_and_validate(
        llm, view_query, view=view, min_confidence=min_confidence, max_attempts=max_attempts
    )

    reused = find_reusable_dataset(view=view, session_id=session_id, conversation_id=conversation_id, plan=plan)
    df = load_reused_df(reused.id) if reused else None
    if df is not None:
        if on_stage:
            on_stage("reuse" + stage_suffix)
    else:
        reused = None  # loading the reused dataset failed — fetch fresh instead
        if on_stage:
            on_stage("fetch" + stage_suffix)
        df = view.execute(plan)
        save_to_catalog(session_id=session_id, conversation_id=conversation_id, query=view_query, plan=plan, df=df)

    return ViewResult(
        query=view_query, plan=plan, df=df, attempts=attempts,
        reused_dataset_id=reused.id if reused else None,
    )
