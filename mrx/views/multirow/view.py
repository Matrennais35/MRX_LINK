"""MultirowView — the first View implementation.

Thin delegation to the existing multirow modules (generate_link / validation /
data_fetch): the actual planning/validation/fetching logic is unchanged, it's
just reached through the View interface now instead of imported directly by
the core. This is what makes multirow a plug-in rather than a hard-wired view.
"""

import pandas as pd

from ...pipeline import data_fetch
from ...pipeline.models import MRXPlan
from . import generate_link
from . import validation


class MultirowView:
    """The Multirow Risk Snapshot view — today's only view. Implements the
    View protocol (mrx/views/base.py) by delegating to the multirow modules.
    """

    name = "multirow"
    description = (
        "Multirow Risk Snapshot: risk figures (Delta, Vega, PV, etc.) for a "
        "node/perimeter over a date range, broken down by a chosen row grouping "
        "(risk type, desk, product, deal, ...)."
    )

    def plan(self, llm, query: str, *, prior_attempts=()) -> MRXPlan:
        return generate_link.get_link(llm, query, prior_attempts=prior_attempts)

    def validate(self, plan: MRXPlan, *, min_confidence: float = 0.7) -> None:
        validation.validate_plan(plan, min_confidence=min_confidence)

    def execute(self, plan: MRXPlan) -> pd.DataFrame:
        return data_fetch.fetch_data(plan.url)

    def fingerprint(self, plan: MRXPlan) -> dict:
        return validation.parse_mrx_url(plan.url)
