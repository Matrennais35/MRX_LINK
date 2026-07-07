"""The OPTIONAL tested analysis library — available inside run_python's
namespace (leaf-aware math, trend, position_change, chart builders), never
mandated: free pandas is always legal. Generic math only; anything MRX can
serve natively is fetched, not recomputed (see VISION.md)."""

from . import charts, ops
