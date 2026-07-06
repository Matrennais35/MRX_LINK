"""The audit trace: one Step per agent decision, tool run, or gate event.

A single record type used in memory AND persisted (mapped onto the catalog's
steps table at turn-save time) — the old code's StepRecord/StepTrace split plus
a manual converter is deliberately gone. Every agent run and tool run flows
through the wrappers here, so the trace is uniform by construction rather than
by discipline.
"""

import time
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Step:
    kind: str                    # "agent" | "tool" | "gate"
    name: str                    # role name / tool name / gate name
    summary: str                 # one line for the UI trace
    detail: dict = field(default_factory=dict)   # full structured record (audit)
    status: str = "ok"           # "ok" | "failed" | "refused"
    elapsed_ms: int = 0


def timed(fn):
    """Run `fn()` returning (result, elapsed_ms) — trace timing helper."""
    start = time.monotonic()
    result = fn()
    return result, int((time.monotonic() - start) * 1000)
