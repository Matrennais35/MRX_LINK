"""ToolSession — the Executor's state for one question.

Holds the persistent python namespace (fetched frames by label + pd/plt/
helpers + section()), the collected report artifacts, the evidence list, the
HARD fetch budget, and the trace. Duck-types the fields the gated fetch
(tools/mrx_fetch.fetch_evidence) expects, so that proven machinery is reused
unchanged.
"""

import threading
from dataclasses import dataclass, field
from typing import Callable, List, Optional, TYPE_CHECKING

from ..common.errors import BudgetExhausted
from ..common.events import no_emit
from ..common.trace import Step

if TYPE_CHECKING:
    from ..mrx.profiler import DataProfile

DEFAULT_MAX_FETCHES = 6


@dataclass
class FetchBudget:
    """Hard cap on fresh MRX fetches per question — plain code that raises,
    never a knob a model or framework holds. Locked: parallel fetches must
    keep the cap exact."""

    max_fetches: int = DEFAULT_MAX_FETCHES
    used: int = 0
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False, compare=False)

    def acquire(self) -> None:
        with self._lock:
            if self.used + 1 > self.max_fetches:
                raise BudgetExhausted(self.used, self.max_fetches)
            self.used += 1


@dataclass
class Evidence:
    """One dataset available to the run — fetched or reused — with its
    deterministic profile."""

    dataset_id: str
    label: str
    plan: object              # mrx.models.MRXPlan or None (computed tables)
    df: object                # pd.DataFrame
    profile: "DataProfile"
    provenance: str           # "fetched" | "reused" | "computed"


@dataclass
class Artifact:
    section: str          # blueprint section title this fills
    kind: str             # "table" | "chart"
    obj: object
    title: str = ""
    full: bool = False    # extraction: render the complete table, no preview cap


@dataclass
class ToolSession:
    session_id: str
    conversation_id: Optional[str] = None
    emit: Callable[[str, dict], None] = no_emit
    budget: FetchBudget = field(default_factory=FetchBudget)
    evidence: List = field(default_factory=list)      # Evidence entries (fetch_evidence appends)
    trace: List[Step] = field(default_factory=list)
    namespace: dict = field(default_factory=dict)     # the per-question python namespace
    artifacts: List[Artifact] = field(default_factory=list)
    code_log: List[str] = field(default_factory=list)

    def install_namespace(self) -> None:
        """Seed the namespace: pandas/matplotlib, the OPTIONAL tested helpers
        library, and section() — the delivery convention that attaches a
        computed artifact to a blueprint section. Free pandas is always legal;
        nothing routes through helpers."""
        import matplotlib.pyplot as plt
        import numpy as np
        import pandas as pd

        from .. import helpers

        session = self

        def section(title: str, table=None, chart=None, full=False):
            """Attach artifact(s) to the report section `title`. Pass
            full=True for EXTRACTION answers so the UI shows every row.
            Attached tables are ECHOED to stdout so the model HOLDS the
            values verbatim when it writes the note (the LLM_CCR comparison:
            prose written from summaries reads thin)."""
            if table is not None:
                session.artifacts.append(Artifact(section=title, kind="table", obj=table, full=full))
                try:
                    print(f"[section {title!r}] table attached "
                          f"({len(table)} rows):\n{table.head(25).to_string()}")
                except Exception:
                    pass
            if chart is not None:
                session.artifacts.append(Artifact(section=title, kind="chart", obj=chart))
            return f"section({title!r}): attached " + ", ".join(
                k for k, v in (("table", table), ("chart", chart)) if v is not None
            )

        self.namespace.update({"pd": pd, "np": np, "plt": plt,
                               "helpers": helpers, "section": section})

    def register_frame(self, label: str, df) -> None:
        self.namespace[label] = df

    def artifacts_for(self, title: str) -> List[Artifact]:
        key = title.strip().casefold()
        return [a for a in self.artifacts if a.section.strip().casefold() == key]
