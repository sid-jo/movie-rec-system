"""
Importable pipeline entrypoints (ingest → transform → train).

Each module provides a `run(...)` function plus a CLI:
  python -m pipeline.ingest ...
  python -m pipeline.transform ...
  python -m pipeline.train ...

Offline eval: use scripts/offline_eval.py (writes models/artifacts/offline_eval.json).
"""

