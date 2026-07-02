"""Decide, per question, whether to reuse an already-fetched dataset or
fetch new data — reuse-first, decided deterministically (no LLM judgment
call trusted for this), plus (for later phases) an LLM call that decomposes
a question into one or more views to fetch.

Reuse-vs-fetch does NOT need its own LLM call: the thing that determines
whether a stored dataset covers a new question is the same MRXPlan/URL the
existing planning stage (generate_link.get_link) already builds for that
question — planning is cheap, the MRX *fetch* is the expensive step this
whole feature exists to skip. So the pipeline always plans first (as it
always has), then `find_reusable_dataset` checks the resulting URL's
parsed params against the catalog in plain Python. This mirrors
validation.py's "never trust the LLM's own output, verify it deterministically
against the manual's tables" philosophy — here applied to reuse instead of
mandatory-params/code-legality.

`route()` below is for a DIFFERENT decision — single vs. multiple views for
one question (e.g. "analyse X by desk, product, and deal" implies three
fetches) — which genuinely does require judgment a fixed rule can't make.
Not wired into the orchestrator until multi-fetch is built (phase 3); kept
here now since it's a small, self-contained addition and the schema is
already settled.
"""

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field
from langchain_core.messages import HumanMessage, SystemMessage

from . import validation
from .catalog import Dataset
from .pipeline_errors import PlanValidationError

# Params that must match exactly for a stored dataset to be considered the
# "same view" as a new fetch would produce: risk type, node/underlying, and
# every row-level grouping (by-desk, by-deal, by-product, etc all live in
# these — see validation.ROW_LEVEL_PARAMS). Comparing only p1217 would miss
# a "split by top deals" follow-up landing in p1218/p1219 instead, and
# falsely allow reuse across two different breakdowns of the same data.
_DIMENSION_PARAMS = ["p13", "p1"] + validation.ROW_LEVEL_PARAMS


def _dates_cover(dataset_params: dict, query_params: dict) -> bool:
    """Does the dataset's [p28, p27] (start, end) date range cover the
    range a fresh fetch for the new question would use? Both use the same
    p27=end/p28=start convention as the rest of this codebase.

    Conservative by construction: any missing/unparseable date on either
    side returns False (don't reuse) rather than guessing coverage.
    """
    def _parse(params, key):
        value = params.get(key)
        if not value:
            return None
        try:
            return datetime.strptime(value, "%Y-%m-%d")
        except ValueError:
            return None

    ds_start, ds_end = _parse(dataset_params, "p28"), _parse(dataset_params, "p27")
    q_start, q_end = _parse(query_params, "p28"), _parse(query_params, "p27")
    if not all([ds_start, ds_end, q_start, q_end]):
        return False
    return ds_start <= q_start and q_end <= ds_end


def _covers(dataset: Dataset, plan_url: str) -> bool:
    """Does `dataset` already contain everything a fresh fetch of
    `plan_url` would produce? Never raises — an unparseable URL on either
    side is treated as "does not cover" (fail closed), same stance
    validation.py takes when a param can't be checked.
    """
    try:
        dataset_params = validation.parse_mrx_url(dataset.plan.url)
        query_params = validation.parse_mrx_url(plan_url)
    except PlanValidationError:
        return False

    for param in _DIMENSION_PARAMS:
        if dataset_params.get(param) != query_params.get(param):
            return False

    return _dates_cover(dataset_params, query_params)


def find_reusable_dataset(datasets: list, plan_url: str) -> Optional[Dataset]:
    """Return the first catalog entry (already session-ranked by the
    caller, see catalog.list_all) whose stored data covers `plan_url`, or
    None if nothing qualifies. Callers should fetch fresh data when this
    returns None — this function only ever says "yes, reuse this" when the
    match is exact on dimensions and date coverage; it never guesses.
    """
    for dataset in datasets:
        if _covers(dataset, plan_url):
            return dataset
    return None


# ---------------------------------------------------------------------------
# Multi-view decomposition (not yet wired into the orchestrator — phase 3)
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """\
You decide whether a market-risk question needs one MRX view or several.

Choose exactly one mode:
- "single_fetch": one MRX fetch answers this question. Put the (possibly
  rephrased) question as the one entry in new_view_queries.
- "multi_fetch": this question genuinely requires several distinct views
  (e.g. "analyse the variation... by desk, product, and deal" implies
  fetching a by-desk view, a by-product view, and a by-deal view
  separately). List each view as its own natural-language sub-question in
  new_view_queries.

Prefer "single_fetch" unless the question explicitly asks for an analysis
spanning multiple breakdowns or comparisons that no single MRX view can
produce at once.
"""


class RoutingDecision(BaseModel):
    mode: Literal["single_fetch", "multi_fetch"]
    reasoning: str = Field(description="Why this mode and these view queries")
    new_view_queries: list[str] = Field(default_factory=list)


def route(llm, query: str) -> RoutingDecision:
    """Ask the LLM whether `query` needs one MRX view or several, and if
    several, what each one should ask for. Does not consider the catalog —
    reuse is already handled deterministically by find_reusable_dataset
    before this would ever be called.
    """
    messages = [
        SystemMessage(content=SYSTEM_PROMPT),
        HumanMessage(content=f"Question: {query}"),
    ]
    structured_llm = llm.with_structured_output(RoutingDecision)
    return structured_llm.invoke(messages)
