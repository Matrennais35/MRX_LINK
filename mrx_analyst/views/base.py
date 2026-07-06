"""The View interface: what the pipeline needs from an MRX view, so a view
plugs in rather than being hard-imported.

A View owns the four view-specific steps the core otherwise hard-wires to
one view: turn a question into a plan, validate that plan, execute it into a
dataframe, and fingerprint it for reuse-matching. `fetch.get_view` and
`router`'s reuse gate call these instead of importing a specific view's
modules, so adding a second MRX view is "write a View + register it" with no
edits to the loop / fetch / router / catalog / smart_pandas.

Deliberately MRX-flavored: `plan` returns an `MRXPlan` and the catalog still
stores that, so no catalog change is needed (a non-MRX `Source` abstraction
was considered and deferred — see docs/view_interface_design.md). But the
SHAPE here — plan / validate / execute / fingerprint — is the shape a future
Source would have, so this widens into Source by loosening types rather than
a redesign, if a non-MRX input ever becomes real.
"""

from typing import Protocol, runtime_checkable

import pandas as pd

from ..core.models import MRXPlan


@runtime_checkable
class View(Protocol):
    """One MRX report type the pipeline can plan against, fetch, and reuse.

    `name` is the registry key; `description` says what the view answers (for
    a future per-question view-selection step — only one view exists today, so
    nothing selects yet, but the interface makes it possible without a later
    redesign).
    """

    name: str
    description: str

    def plan(self, llm, query: str, *, prior_attempts=()) -> MRXPlan:
        """Turn a natural-language question into a validated-shape MRXPlan.
        `prior_attempts` carries (plan, error) pairs from earlier failed
        attempts so the LLM can self-correct (see fetch.plan_and_validate).
        """
        ...

    def validate(self, plan: MRXPlan, *, min_confidence: float = 0.7) -> None:
        """Raise PlanValidationError if `plan` is unsafe or malformed. This is
        the mandatory gate every fetch passes through — never bypassed.
        """
        ...

    def execute(self, plan: MRXPlan) -> pd.DataFrame:
        """Run the plan against MRX and return the resulting dataframe."""
        ...

    def fingerprint(self, plan: MRXPlan) -> dict:
        """The reuse-matching key for `plan` — a dict of the parameters that
        must match (exactly, modulo date coverage) for a stored dataset to be
        reusable for this plan. See router._covers.
        """
        ...
