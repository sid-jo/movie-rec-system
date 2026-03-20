from __future__ import annotations

import os
from dataclasses import dataclass


def project_root() -> str:
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@dataclass(frozen=True)
class PipelinePaths:
    root: str
    data_raw_logs: str
    data_processed: str
    metadata_dir: str
    model_artifacts: str
    reports_dir: str


def default_paths(root: str | None = None) -> PipelinePaths:
    r = os.path.abspath(root or project_root())
    return PipelinePaths(
        root=r,
        data_raw_logs=os.path.join(r, "data", "raw_logs"),
        data_processed=os.path.join(r, "data", "processed"),
        metadata_dir=os.path.join(r, "metadata"),
        model_artifacts=os.path.join(r, "models", "artifacts"),
        reports_dir=os.path.join(r, "reports"),
    )


def path_relative_to_root(path: str, root: str | None = None) -> str:
    """Return path relative to project root for use in reports (no absolute dirs)."""
    r = os.path.abspath(root or project_root())
    p = os.path.abspath(path)
    rel = os.path.relpath(p, r)
    return rel.replace("\\", "/")

