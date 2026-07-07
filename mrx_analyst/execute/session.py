"""ToolSession — the Executor's state for one question.

Holds the persistent python namespace (fetched frames by label + pd/plt/
helpers + section()), the collected report artifacts, the evidence list, the
HARD fetch budget, and the trace. Duck-types the fields the gated fetch
(tools/mrx_fetch.fetch_evidence) expects, so that proven machinery is reused
unchanged.
"""

from dataclasses import dataclass, field
from typing import Callable, List, Optional

from ..common.events import no_emit
from ..common.trace import Step
from ..core.context import FetchBudget


@dataclass
class Artifact:
    section: str          # blueprint section title this fills
    kind: str             # "table" | "chart"
    obj: object
    title: str = ""


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

        def section(title: str, table=None, chart=None):
            """Attach artifact(s) to the report section `title`."""
            if table is not None:
                session.artifacts.append(Artifact(section=title, kind="table", obj=table))
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
