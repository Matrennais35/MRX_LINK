"""BRIDGE RUN — the full framework, locally: sim data + a file-bridged LLM.

The LLM calls are written to .bridge/ as request files; an external operator
(Claude Code spawning a FRESH subagent per request — stateless, like an API)
services them. Everything else — validation gate, budget, profiler, helpers,
writer, critic, persistence — is the real code. Output: the same report as
slice_run.
"""

import sys
import types

# Local machine has no pymrx/httpx_auth — stub before any framework import.
sys.modules.setdefault("pymrx", types.ModuleType("pymrx"))
_h = sys.modules.setdefault("httpx_auth", types.ModuleType("httpx_auth"))
_h.OAuth2ClientCredentials = getattr(_h, "OAuth2ClientCredentials", object)

import matplotlib
matplotlib.use("Agg")

import os
os.environ["MRX_SIM"] = "1"

import textwrap

from mrx_analyst import run as runner
from mrx_analyst.common.bridge import FileBridgeLLM
from mrx_analyst.storage import catalog

QUESTION = os.environ.get(
    "BRIDGE_QUESTION",
    "Analyse the variation of FX Vega on GFXOPEMK over the last month.")

llm = FileBridgeLLM(".bridge")
conversation_id = catalog.new_conversation_id()
print(f"QUESTION: {QUESTION}\nbridge dir: .bridge/  conversation: {conversation_id}",
      flush=True)


def emit(kind, payload):
    if kind == "status":
        print(f"  · {payload['label']}", flush=True)
    elif kind == "fetch":
        print(f"  · fetch {payload.get('stage')}: {payload.get('label','')[:80]}", flush=True)


result = runner.run_question(llm, QUESTION, session_id="bridge",
                             conversation_id=conversation_id, emit=emit)

line = "=" * 78
print(f"\n{line}\nTHE BLUEPRINT\n{line}\n{result.blueprint.render_text()}")
print(f"\n{line}\nTRACE ({len(result.session.trace)} steps)\n{line}")
for i, s in enumerate(result.session.trace, 1):
    flag = "" if s.status == "ok" else f" [{s.status.upper()}]"
    print(f"{i}. [{s.kind}] {s.name}{flag} — {s.summary[:140]}")
print(f"\n{line}\nTHE NOTE\n{line}\n{result.answer.narrative}")
for sec in result.answer.sections:
    print(f"\n## {sec.title}" + ("" if sec.status == "filled" else f" [UNFILLED: {sec.reason}]"))
    if sec.text:
        print(sec.text)
    if sec.table is not None:
        print(textwrap.indent(sec.table.head(12).to_string(), "  "))
    if sec.chart is not None:
        print("  (chart produced)")
print(f"\n{line}\nbudget {result.session.budget.used}/{result.session.budget.max_fetches}"
      f" · python runs {len(result.session.code_log)}"
      f" · timings { {k: round(v,1) for k,v in result.timings.items()} }")
