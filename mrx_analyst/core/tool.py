"""The Tool base: a name + typed Args + run(), executed only via run_tool().

Tools are deterministic capabilities (fetch, profile, attribution, chart
builders, codegen fallback). Agents PROPOSE tool calls as structured output;
the orchestrator EXECUTES them through `run_tool`, which is the single funnel
that traces and emits every execution — the audit trail is uniform by
construction.
"""

from dataclasses import dataclass
from typing import Any, Type

from pydantic import BaseModel

from .context import RunContext
from .events import EventKind
from .trace import Step, timed


@dataclass
class ToolResult:
    value: Any            # df / Figure / DataProfile / dict — whatever the tool yields
    summary: str          # one line for the trace + the next agent's prompt
    audit: dict           # full args + outcome, persisted in the step detail


class Tool:
    """Subclasses set `name`, `description`, `Args` (a pydantic model — bad
    arguments become a structured validation error fed back to the proposing
    agent, not a stack trace), and implement `run(args, ctx)`."""

    name: str = "tool"
    description: str = ""
    Args: Type[BaseModel] = BaseModel

    def run(self, args: BaseModel, ctx: RunContext) -> ToolResult:
        raise NotImplementedError


def run_tool(tool: Tool, args: BaseModel, ctx: RunContext) -> ToolResult:
    """The ONLY way tools execute: uniform emit + trace + timing, success or
    failure. A failing tool records a failed step and re-raises — what to do
    about it (retry, fallback, abort) is the orchestrator's plain-code call.
    """
    ctx.emit(EventKind.TOOL, {"name": tool.name, "args": args.model_dump()})
    try:
        result, elapsed = timed(lambda: tool.run(args, ctx))
    except Exception as e:
        ctx.trace.append(Step(
            kind="tool", name=tool.name, summary=f"failed: {e}",
            detail={"args": args.model_dump(), "error": str(e)},
            status="failed",
        ))
        raise
    ctx.trace.append(Step(
        kind="tool", name=tool.name, summary=result.summary,
        detail=result.audit, elapsed_ms=elapsed,
    ))
    return result
