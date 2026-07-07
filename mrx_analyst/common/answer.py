"""The ONE answer shape — now a desk-style report when the analysis earns it.

Every answer is a narrative (the executive summary) plus whichever artifacts
the question deserved. An ANALYTICAL answer additionally carries ordered
SECTIONS — the report outline the Planner designed up front, each filled with
its own text/chart/table (structure-first: the outline is planned before any
data is touched, and an unfilled section is a VISIBLE gap with a reason, never
a silent drop). Simple answers (lookups, prose) keep sections empty.
"""

from dataclasses import dataclass, field
from typing import List, Optional

import pandas as pd
from matplotlib.figure import Figure


@dataclass
class Section:
    """One report section: the title from the Planner's outline, the Narrator's
    grounded text for it, and the artifact(s) that fill it."""
    title: str
    text: str = ""
    chart: Optional[Figure] = None
    table: Optional[pd.DataFrame] = None
    status: str = "filled"     # "filled" | "unfilled" (visible gap)
    reason: str = ""           # when unfilled: the one-line why
    full_table: bool = False   # extraction mode: render EVERY row (no preview cap)


@dataclass
class Answer:
    narrative: str                          # ALWAYS present — the executive summary
    table: Optional[pd.DataFrame] = None    # primary artifact (simple answers / back-compat)
    chart: Optional[Figure] = None
    value: Optional[str] = None             # a formatted scalar, when the question was a lookup
    sections: List[Section] = field(default_factory=list)  # the desk report, outline order

    @property
    def has_artifacts(self) -> bool:
        return self.table is not None or self.chart is not None or self.value is not None

    @property
    def charts(self) -> List[Figure]:
        """Every distinct figure this answer carries, report order."""
        figures = []
        for section in self.sections:
            if section.chart is not None and section.chart not in figures:
                figures.append(section.chart)
        if self.chart is not None and self.chart not in figures:
            figures.append(self.chart)
        return figures
