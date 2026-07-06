"""The Agent base: a role prompt + a structured Output schema + run().

Design rule for the whole package: **agents propose, code disposes.** An agent
is a single-shot structured-output LLM call (the same `with_structured_output`
mechanism proven in the old pipeline) that renders its own view of the
RunContext and returns a validated object. Every loop, retry cap, budget check,
and tool execution lives in the orchestrator's plain code — no model ever holds
control flow.
"""

from typing import Type

from pydantic import BaseModel

from .context import RunContext
from .events import EventKind
from .trace import Step, timed


class Agent:
    """Subclasses set `role`, `system_prompt`, `Output`, and implement
    `build_messages(ctx)` (the HumanMessage(s) rendering their view of the run).
    """

    role: str = "agent"
    system_prompt: str = ""
    Output: Type[BaseModel] = BaseModel

    def build_messages(self, ctx: RunContext) -> list:
        raise NotImplementedError

    def run(self, llm, ctx: RunContext) -> BaseModel:
        from langchain_core.messages import SystemMessage

        messages = [SystemMessage(content=self.system_prompt)] + self.build_messages(ctx)
        structured = llm.with_structured_output(self.Output)
        out, elapsed = timed(lambda: structured.invoke(messages))
        ctx.trace.append(Step(
            kind="agent", name=self.role,
            summary=_summary_of(out), detail=out.model_dump(), elapsed_ms=elapsed,
        ))
        ctx.emit(EventKind.AGENT, {"role": self.role, "output": out.model_dump()})
        return out


def _summary_of(out: BaseModel) -> str:
    """One trace line from an agent's output: prefer a reasoning-ish field."""
    for name in ("reasoning", "target", "verdict", "approach"):
        value = getattr(out, name, None)
        if isinstance(value, str) and value:
            return value if len(value) <= 200 else value[:197] + "..."
    return type(out).__name__
