"""The ONE answer shape.

Every answer is a narrative plus whichever artifacts the question deserved —
never a 5-way type union (the old code's central mistake: number|string|
dataframe|chart|composed, branched at 16 sites). The UI branches exactly once,
on parts-present: render the narrative, then each part that exists.
"""

from dataclasses import dataclass
from typing import Optional

import pandas as pd
from matplotlib.figure import Figure


@dataclass
class Answer:
    narrative: str                          # ALWAYS present — every answer explains itself
    table: Optional[pd.DataFrame] = None    # the structured breakdown, when data was computed
    chart: Optional[Figure] = None          # the visualization, when one serves the target
    value: Optional[str] = None             # a formatted scalar, when the question was a lookup

    @property
    def has_artifacts(self) -> bool:
        return self.table is not None or self.chart is not None or self.value is not None
