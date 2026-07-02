"""Decide, per question, whether to reuse an already-fetched dataset or
fetch new data — reuse-first, decided deterministically (no LLM judgment
call trusted for this), plus (for later phases) an LLM call that decomposes
a question into one or more views to fetch.

Reuse-vs-fetch does NOT need its own LLM call: the thing that determines
whether a stored dataset covers a new question is the same MRXPlan/URL the
existing planning stage (get_link) already builds for that question —
planning is cheap, the MRX *fetch* is the expensive step this whole
feature exists to skip. So the pipeline always plans first (as it always
has), then `find_reusable_dataset` checks the resulting URL's parsed
params against the catalog in plain Python. This mirrors
validation.py's "never trust the LLM's own output, verify it
deterministically against the manual's tables" philosophy — here applied
to reuse instead of mandatory-params/code-legality.

`route()` below is for a DIFFERENT decision — single vs. multiple views for
one question (e.g. "analyse X by desk, product, and deal" implies three
fetches) — which genuinely does require judgment a fixed rule can't make.
Called by `orchestrator.run` when `allow_multi_fetch=True` (the Streamlit
UI's default); off by default there because it would be a redundant LLM
call for the common single-view question.

NOTE — the one real seam a second MRX view would hit: `_covers()` below
calls `views.multirow.validation.parse_mrx_url()`, which is Multirow-
specific (it checks the URL starts with Multirow's own base URL and
parses `p<ID>=value` query params). This module is otherwise view-
agnostic; that one import is where a genuinely multi-view future would
need `parse_mrx_url`-like logic to become either per-view or generalized.
Left as-is for now (still Multirow-only in practice) rather than
generalized speculatively.
"""

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field
from langchain_core.messages import HumanMessage, SystemMessage

from ..views.multirow import validation
from .catalog import Dataset
from .pipeline_errors import PlanValidationError

# The date params are the ONLY thing allowed to differ between a stored
# dataset and a fresh fetch for reuse to be valid — every other param must
# match exactly. This used to be an allow-list of "dimension" params (risk
# type, node, row grouping), which silently missed result-shape params like
# p1029 (Total snapshot vs. wide history-dates series) and p1021 (Current
# vs. Current/Previous/Difference — 1 vs. up to 3 value columns): a cached
# wide time-series could pass the check for a later point-in-time snapshot
# request and get reused as-is, feeding wrong-shaped data to the answer
# stage with no error anywhere. A deny-list of just the date params closes
# this for every param, including ones added to the manual later.
_DATE_PARAMS = {"p27", "p28"}


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

    non_date_keys = (dataset_params.keys() | query_params.keys()) - _DATE_PARAMS
    for param in non_date_keys:
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
# Multi-view decomposition + answer-from-context (called from
# orchestrator.run when allow_multi_fetch=True)
# ---------------------------------------------------------------------------

SYSTEM_PROMPT_NO_CONTEXT = """\
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

# Used instead of the above once this conversation has at least one
# already-fetched dataset — adds the third mode. Kept as a fully separate
# prompt (not the same one with a conditionally-appended paragraph) so the
# no-context case — still the common case for a first question — stays
# exactly as simple as before this mode existed.
SYSTEM_PROMPT_WITH_CONTEXT = """\
You decide how to answer a market-risk question in an ongoing conversation
that already has fetched data available.

Choose exactly one mode:
- "answer_from_context": the question is a follow-up that can be answered
  purely by analyzing data already fetched in this conversation (e.g. "what
  was the biggest daily variation", "which desk drove that", "sort it by
  product") — no new MRX view is needed. Leave new_view_queries empty.
- "single_fetch": this question needs one NEW MRX fetch — either it's
  unrelated to what's already fetched, or it asks for data (a different
  date range, risk type, node, or breakdown) that the existing data
  doesn't contain. Put the (possibly rephrased) question as the one entry
  in new_view_queries.
- "multi_fetch": this question genuinely requires several distinct NEW
  views (e.g. "analyse the variation... by desk, product, and deal"
  implies fetching a by-desk view, a by-product view, and a by-deal view
  separately). List each view as its own natural-language sub-question in
  new_view_queries.

Here is a description of what's already been fetched in this conversation:

{context_summary}

Prefer "answer_from_context" whenever the existing data already contains
what the question needs — a new MRX fetch is slow and should only happen
when the question genuinely can't be answered from what's already there.
"""


class RoutingDecision(BaseModel):
    mode: Literal["answer_from_context", "single_fetch", "multi_fetch"]
    reasoning: str = Field(description="Why this mode and these view queries")
    new_view_queries: list[str] = Field(default_factory=list)


def _describe_dataset(dataset: Dataset) -> str:
    columns = ", ".join(dataset.schema) if dataset.schema else "(schema unknown)"
    return f"- {dataset.description} (from: {dataset.query!r}) — columns: {columns}"


def route(llm, query: str, *, context_datasets: Optional[list] = None) -> RoutingDecision:
    """Ask the LLM how to answer `query`: from already-fetched data, one
    new MRX fetch, or several. Does not consider the catalog for the
    single_fetch/multi_fetch reuse question — that's still handled
    deterministically by find_reusable_dataset once a plan/URL exists.
    This call only decides whether a NEW fetch is needed at all.

    `context_datasets`, if given a non-empty list (typically
    catalog.list_for_conversation(conversation_id=...)), switches to the
    3-mode prompt that offers "answer_from_context"; omitted or empty, this
    behaves exactly as it did before that mode existed (no prompt or
    schema change for the common first-question-in-a-conversation case).
    """
    if context_datasets:
        context_summary = "\n".join(_describe_dataset(d) for d in context_datasets)
        system_prompt = SYSTEM_PROMPT_WITH_CONTEXT.format(context_summary=context_summary)
    else:
        system_prompt = SYSTEM_PROMPT_NO_CONTEXT

    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=f"Question: {query}"),
    ]
    structured_llm = llm.with_structured_output(RoutingDecision)
    return structured_llm.invoke(messages)
