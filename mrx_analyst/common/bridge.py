"""FileBridgeLLM — an LLM served through the filesystem.

Duck-types the langchain client the framework uses (invoke /
with_structured_output / bind_tools) but, instead of calling an API, writes
each request as JSON into BRIDGE_DIR and BLOCKS until a response file
appears. An external operator (a human, or Claude Code spawning a FRESH
subagent per request — no shared context, exactly like a stateless API call)
services the requests.

Purpose: run the ENTIRE framework locally — real prompts, real tool loop,
sim data — without APIGEE. The operator sees exactly what gpt55 would see.

Request file:  req_<id>.json   {kind, messages, schema?|tools?}
Response file: res_<id>.json   structured -> the schema object;
                               tools -> {content, tool_calls:[{name,args}]};
                               text -> {content}
"""

import json
import re
import time
import uuid
from pathlib import Path

from langchain_core.messages import AIMessage

POLL_S = 2
TIMEOUT_S = 1800


def _serialize_messages(messages) -> list:
    if isinstance(messages, str):
        return [{"role": "human", "content": messages}]
    out = []
    for m in messages:
        entry = {"role": m.type, "content": m.content if isinstance(m.content, str) else str(m.content)}
        if getattr(m, "tool_calls", None):
            entry["tool_calls"] = [{"name": tc["name"], "args": tc["args"]}
                                   for tc in m.tool_calls]
        if getattr(m, "tool_call_id", None):
            entry["tool_call_id"] = m.tool_call_id
        out.append(entry)
    return out


def _strip_fences(text: str) -> str:
    text = text.strip()
    match = re.match(r"^```(?:json)?\s*(.*?)\s*```$", text, re.DOTALL)
    return match.group(1) if match else text


class FileBridgeLLM:
    def __init__(self, bridge_dir: str = ".bridge"):
        self.dir = Path(bridge_dir)
        self.dir.mkdir(parents=True, exist_ok=True)

    # -- the three call styles the framework uses ---------------------------
    def invoke(self, messages):
        payload = self._roundtrip({"kind": "text",
                                   "messages": _serialize_messages(messages)})
        return AIMessage(content=payload.get("content", ""))

    def with_structured_output(self, schema):
        outer = self

        class _Structured:
            def invoke(self, messages):
                payload = outer._roundtrip({
                    "kind": "structured",
                    "schema_name": schema.__name__,
                    "json_schema": schema.model_json_schema(),
                    "messages": _serialize_messages(messages),
                })
                return schema.model_validate(payload)
        return _Structured()

    def bind_tools(self, tools):
        outer = self
        tool_specs = [{"name": t.__name__, "description": (t.__doc__ or "").strip(),
                       "parameters": t.model_json_schema()} for t in tools]

        class _Tools:
            def invoke(self, messages):
                payload = outer._roundtrip({
                    "kind": "tools", "tools": tool_specs,
                    "messages": _serialize_messages(messages),
                })
                calls = [{"name": tc["name"], "args": tc.get("args", {}),
                          "id": f"call_{uuid.uuid4().hex[:8]}", "type": "tool_call"}
                         for tc in payload.get("tool_calls", [])]
                return AIMessage(content=payload.get("content", ""), tool_calls=calls)
        return _Tools()

    # -- the filesystem round-trip -------------------------------------------
    def _roundtrip(self, request: dict) -> dict:
        rid = uuid.uuid4().hex[:10]
        req, res = self.dir / f"req_{rid}.json", self.dir / f"res_{rid}.json"
        tmp = self.dir / f"tmp_{rid}.json"
        tmp.write_text(json.dumps(request, ensure_ascii=False, indent=1),
                       encoding="utf-8")
        tmp.rename(req)  # atomic appearance — the operator never sees a partial file
        deadline = time.time() + TIMEOUT_S
        while time.time() < deadline:
            if res.exists():
                time.sleep(0.2)  # let the writer finish
                raw = _strip_fences(res.read_text(encoding="utf-8"))
                return json.loads(raw)
            time.sleep(POLL_S)
        raise TimeoutError(f"bridge: no response for {req.name} within {TIMEOUT_S}s")
