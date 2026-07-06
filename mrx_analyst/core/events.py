"""The ONE event channel between the pipeline and any frontend.

Everything the run wants to surface live — agent decisions, tool calls, fetch
progress, streamed narrative tokens — goes through a single `emit(kind,
payload)` callable carried on the RunContext. The UI installs one handler and
routes by `kind`; headless runs use the no-op. This replaces the old app's
three parallel callback channels (on_stage/on_step/on_token).
"""


class EventKind:
    """The vocabulary of `kind` values. Plain constants, not an Enum — payloads
    are dicts and frontends switch on strings; keep the seam simple."""

    AGENT = "agent"        # an agent produced its structured output {role, output}
    TOOL = "tool"          # a tool is being run {name, args}
    FETCH = "fetch"        # fetch lifecycle {stage: planned|reused|fetching|done|failed, label, url?}
    TOKEN = "token"        # streamed narrative text {text: accumulated_buffer}
    STATUS = "status"      # coarse progress label {label}
    ERROR = "error"        # a surfaced failure {message, url?}


def no_emit(kind: str, payload: dict) -> None:
    """The default emit: headless runs (tests, scripts) ignore events."""
