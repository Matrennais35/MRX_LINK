"""The single mutable run state, threaded through every agent and tool.

`RunContext` replaces the old code's per-function parameter threading (plan=None,
history=(), gathered, three callbacks through every signature). Agents render
their own view of it; the orchestrator owns its mutation.

`FetchBudget` is the hard global cap on MRX fetches per turn — plain code that
raises, never a knob handed to a model or a framework (settled with evidence:
framework iteration caps drift; this touches a production risk system).
"""

from dataclasses import dataclass, field
from typing import Callable, List, Optional, TYPE_CHECKING

import pandas as pd

from .errors import BudgetExhausted
from .events import no_emit
from .trace import Step
from .models import MRXPlan

if TYPE_CHECKING:  # profile is produced by tools.profiler (M2); duck-typed here
    from ..tools.profiler import DataProfile


DEFAULT_MAX_FETCHES = 6


@dataclass
class FetchBudget:
    """Hard cap on fresh MRX fetches per turn. `acquire()` is called by the
    orchestrator's fetch phase immediately before each fresh fetch; reused
    datasets cost nothing. Exhaustion raises — the orchestrator catches it,
    records a "gate" step, and proceeds with the evidence gathered so far.
    """

    max_fetches: int = DEFAULT_MAX_FETCHES
    used: int = 0

    def acquire(self) -> None:
        if self.used + 1 > self.max_fetches:
            raise BudgetExhausted(self.used, self.max_fetches)
        self.used += 1


@dataclass
class Evidence:
    """One dataset available to the run — freshly fetched or reused — together
    with its deterministic profile. Agents reason over labels + profiles, never
    raw frames; the Analyst's tool calls reference datasets by `label`.
    """

    dataset_id: str
    label: str                      # sanitized identifier tool calls/codegen refer to
    plan: MRXPlan
    df: pd.DataFrame
    profile: "DataProfile"          # tools.profiler.DataProfile (duck-typed pre-M2)
    provenance: str                 # "fetched" | "reused"


@dataclass
class RunContext:
    query: str
    session_id: str
    conversation_id: Optional[str] = None
    turn_id: str = ""
    history: List[object] = field(default_factory=list)      # prior catalog.Turn rows
    plan: Optional[object] = None                            # agents.planner.AnalysisPlan
    evidence: List[Evidence] = field(default_factory=list)
    budget: FetchBudget = field(default_factory=FetchBudget)
    emit: Callable[[str, dict], None] = no_emit
    trace: List[Step] = field(default_factory=list)
