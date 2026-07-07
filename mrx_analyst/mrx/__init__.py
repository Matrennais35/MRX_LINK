"""The MRX interface machinery: URL building (generate_link), the validation
gate, download (data_fetch), the deterministic reuse gate, the MRXPlan
contract, and the MRX-frame-aware profiler.

Deliberately side-effect-free __init__: importing `mrx_analyst.mrx.models`
(e.g. from storage) must never drag pymrx into the import chain. The concrete
view registry lives in `registry.py`.
"""
