"""
A/B Experimentation Framework for the Movie Recommendation Service.

Supports running multiple concurrent experiments with deterministic user
assignment, variant routing, and telemetry tagging for downstream analysis.

Design:
  - Users are assigned to variants via a deterministic hash of (experiment_id, user_id).
  - Experiment configs are stored as JSON files in experiments/ directory.
  - Each recommendation response is tagged with experiment/variant metadata
    so that the analysis pipeline can attribute outcomes to the correct arm.
"""
import hashlib
import json
import os
import time
import logging
from dataclasses import dataclass, field, asdict
from typing import Optional

logger = logging.getLogger(__name__)

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXPERIMENTS_DIR = os.path.join(PROJECT_ROOT, "experiments")
EXPERIMENT_LOG_PATH = os.path.join(PROJECT_ROOT, "experiments", "logs")


@dataclass
class Variant:
    """One arm of an experiment."""
    name: str                    # e.g. "control", "treatment"
    description: str             # human-readable description
    traffic_pct: float           # 0.0 - 1.0, fraction of traffic
    model_params: dict = field(default_factory=dict)  # variant-specific params


@dataclass
class Experiment:
    """An A/B experiment definition."""
    id: str                      # unique experiment identifier
    name: str                    # human-readable name
    description: str
    variants: list               # list of Variant dicts
    status: str = "active"       # active | paused | completed
    created_at: str = ""
    started_at: str = ""

    def __post_init__(self):
        if not self.created_at:
            self.created_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        if not self.started_at:
            self.started_at = self.created_at
        # Ensure variants are Variant objects
        parsed = []
        for v in self.variants:
            if isinstance(v, dict):
                parsed.append(Variant(**v))
            else:
                parsed.append(v)
        self.variants = parsed


def assign_variant(experiment_id: str, user_id: str, variants: list) -> Variant:
    """
    Deterministically assign a user to an experiment variant.

    Uses a stable hash of (experiment_id, user_id) mapped to [0, 1) and
    walks the variant traffic_pct thresholds to pick the bucket.
    """
    key = f"{experiment_id}:{user_id}"
    h = int(hashlib.sha256(key.encode()).hexdigest(), 16)
    bucket = (h % 10000) / 10000.0  # uniform in [0, 1)

    cumulative = 0.0
    for variant in variants:
        cumulative += variant.traffic_pct
        if bucket < cumulative:
            return variant
    # Fallback to last variant (handles floating point rounding)
    return variants[-1]


class ExperimentManager:
    """Manages experiment lifecycle: loading, assignment, and logging."""

    def __init__(self, experiments_dir: str = EXPERIMENTS_DIR):
        self.experiments_dir = experiments_dir
        self.log_dir = os.path.join(experiments_dir, "logs")
        os.makedirs(self.experiments_dir, exist_ok=True)
        os.makedirs(self.log_dir, exist_ok=True)
        self._experiments: dict[str, Experiment] = {}
        self._load_all()

    def _load_all(self):
        """Load all experiment configs from disk."""
        for fname in os.listdir(self.experiments_dir):
            if fname.endswith(".json") and not fname.startswith("_"):
                path = os.path.join(self.experiments_dir, fname)
                try:
                    with open(path) as f:
                        data = json.load(f)
                    exp = Experiment(**data)
                    self._experiments[exp.id] = exp
                except Exception as e:
                    logger.warning("Failed to load experiment %s: %s", fname, e)

    def get_active_experiments(self) -> list:
        """Return all active experiments."""
        return [e for e in self._experiments.values() if e.status == "active"]

    def get_experiment(self, experiment_id: str) -> Optional[Experiment]:
        return self._experiments.get(experiment_id)

    def get_variant_for_user(self, experiment_id: str, user_id: str) -> Optional[Variant]:
        """Assign a user to a variant for the given experiment."""
        exp = self._experiments.get(experiment_id)
        if not exp or exp.status != "active":
            return None
        return assign_variant(experiment_id, user_id, exp.variants)

    def get_all_assignments(self, user_id: str) -> dict:
        """Return {experiment_id: variant_name} for all active experiments."""
        assignments = {}
        for exp in self.get_active_experiments():
            variant = assign_variant(exp.id, user_id, exp.variants)
            assignments[exp.id] = variant.name
        return assignments

    def save_experiment(self, experiment: Experiment):
        """Persist experiment config to disk."""
        self._experiments[experiment.id] = experiment
        path = os.path.join(self.experiments_dir, f"{experiment.id}.json")
        data = asdict(experiment)
        with open(path, "w") as f:
            json.dump(data, f, indent=2)

    def log_assignment(self, experiment_id: str, user_id: str, variant_name: str,
                       recommendations: list):
        """Append an assignment record to the experiment log (JSONL)."""
        log_path = os.path.join(self.log_dir, f"{experiment_id}.jsonl")
        record = {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "experiment_id": experiment_id,
            "user_id": str(user_id),
            "variant": variant_name,
            "recommendations": recommendations[:20],
        }
        with open(log_path, "a") as f:
            f.write(json.dumps(record) + "\n")


# ---------------------------------------------------------------------------
# Module-level singleton for the Flask app
# ---------------------------------------------------------------------------
_manager: Optional[ExperimentManager] = None


def get_manager() -> ExperimentManager:
    global _manager
    if _manager is None:
        _manager = ExperimentManager()
    return _manager
