"""mrx_analyst — agent-based rebuild of the MRX market-risk analysis assistant.

Same goal as the original pipeline (NL question -> reasoned plan -> validated
MRX fetches -> analysis -> analyst-grade answer), rebuilt with specialized
agents per stage (Planner -> DataScout -> Analyst -> Narrator -> Critic)
dispatched by a plain-code orchestrator, and deterministic tools (dimension
discovery, data profiler, tested analysis toolkit, validated fetch).

Layout: core/ (abstractions + orchestrator), agents/ (the five roles),
tools/ (deterministic capabilities), views/ (MRX view plug-ins + reference
knowledge), storage/ (catalog + feedback), ui/ (Streamlit frontend).
See docs/ + the approved rebuild plan for the design decisions.
"""
