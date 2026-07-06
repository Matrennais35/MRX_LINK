"""Decide, deterministically, whether an already-fetched dataset can be
reused for a new question instead of fetching it again — reuse-first, with
no LLM judgment call trusted for this.

Reuse-vs-fetch does NOT need an LLM call: the thing that determines whether
a stored dataset covers a new question is the same MRXPlan the planning stage
already builds for that question — planning is cheap, the MRX *fetch* is the
expensive step this feature exists to skip. So the pipeline always plans
first, then `find_reusable_dataset` checks the plan's fingerprint against the
catalog in plain Python. This mirrors validation's "never trust the LLM's own
output, verify it deterministically" philosophy — here applied to reuse.

(The former LLM `route()` call — a single up-front single/multi/answer-from-
context classification — was removed when the pipeline consolidated onto the
controller loop, which decides what to fetch one step at a time instead. See
mrx/pipeline/step.py for that per-step decision.)

This module is fully view-agnostic: it never parses a URL itself. The active
view supplies a `fingerprint(plan) -> dict` function (see mrx/views/base.py),
and `_covers` compares two plans' fingerprints. Adding a second MRX view means
supplying its own fingerprint; nothing here changes. (The date-coverage check
below still assumes the fingerprint exposes p27/p28-style start/end dates,
which every MRX view shares — a genuinely different date convention would
generalize `_dates_cover`, but that's not a URL-parsing coupling.)
"""

from datetime import datetime
from typing import Callable, Optional

from ..core.models import MRXPlan
from ..core.errors import PlanValidationError

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


def _covers(dataset, plan: MRXPlan, fingerprint: Callable[[MRXPlan], dict]) -> bool:
    """Does `dataset` already contain everything a fresh fetch of `plan` would
    produce? `fingerprint` turns a plan into its reuse-matching param dict (the
    view supplies it — see fetch.find_reusable_dataset). Never raises — an
    unparseable plan on either side is treated as "does not cover" (fail
    closed), same stance validation takes when a param can't be checked.
    """
    try:
        dataset_params = fingerprint(dataset.plan)
        query_params = fingerprint(plan)
    except PlanValidationError:
        return False

    non_date_keys = (dataset_params.keys() | query_params.keys()) - _DATE_PARAMS
    for param in non_date_keys:
        if dataset_params.get(param) != query_params.get(param):
            return False

    return _dates_cover(dataset_params, query_params)


def find_reusable_dataset(datasets: list, plan: MRXPlan, *, fingerprint: Callable[[MRXPlan], dict]):
    """Return the first catalog entry (already session-ranked by the caller,
    see catalog.list_all) whose stored data covers `plan`, or None if nothing
    qualifies. `fingerprint` (from the active view) computes the reuse-matching
    key for a plan. Callers should fetch fresh data when this returns None —
    this only ever says "yes, reuse this" when the match is exact on dimensions
    and date coverage; it never guesses.
    """
    for dataset in datasets:
        if _covers(dataset, plan, fingerprint):
            return dataset
    return None
