"""
Model variant implementations for A/B experiments.

Each function takes the same signature as get_recommendations() and implements
a specific variant behaviour.  The experiment framework routes requests to
the appropriate variant based on user assignment.
"""
import os
import json
import numpy as np
import joblib

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODELS_DIR = os.path.join(PROJECT_ROOT, "models", "artifacts")
METADATA_DIR = os.path.join(PROJECT_ROOT, "metadata")

# Lazy-loaded movie cost data
_movie_costs = None


def _load_movie_costs():
    """Load movie cost metadata (license cost per view)."""
    global _movie_costs
    if _movie_costs is None:
        path = os.path.join(METADATA_DIR, "movies.json")
        if os.path.exists(path):
            with open(path) as f:
                movies = json.load(f)
            _movie_costs = {}
            for mid, data in movies.items():
                if isinstance(data, dict):
                    cost = data.get("license_cost") or data.get("cost") or 0.0
                    try:
                        _movie_costs[mid] = float(cost)
                    except (ValueError, TypeError):
                        _movie_costs[mid] = 0.0
        else:
            _movie_costs = {}
    return _movie_costs


# ---------------------------------------------------------------------------
# Experiment 1 variants: Cold-start with vs without self-descriptions
# ---------------------------------------------------------------------------

def recommend_with_cold_start(user_id, user_data=None, **kwargs):
    """
    Control: Standard recommendation path (cold-start enabled).
    Identical to the default get_recommendations().
    """
    from src.recommender import get_recommendations
    return get_recommendations(user_id, user_data=user_data, force_popularity=False)


def recommend_without_cold_start(user_id, user_data=None, **kwargs):
    """
    Treatment: Skip the cold-start self-description analysis entirely.
    For new/unknown users this falls through to NMF (if known) or popularity.
    This lets us measure the isolated impact of using self-descriptions.
    """
    from src.recommender import get_recommendations
    # Pass user_data=None to disable the cold-start path that uses
    # self_description_likes / self_description_dislikes
    return get_recommendations(user_id, user_data=None, force_popularity=False)


# ---------------------------------------------------------------------------
# Experiment 2 variants: Cost-optimised recommendations
# ---------------------------------------------------------------------------

def recommend_standard(user_id, user_data=None, **kwargs):
    """
    Control: Standard recommendation path (cost-agnostic).
    """
    from src.recommender import get_recommendations
    return get_recommendations(user_id, user_data=user_data, force_popularity=False)


def _apply_cost_rerank(user_id, base_recs):
    """
    Re-rank an existing recommendation list to prefer cheaper-to-license movies.

    Strategy: expand to top-40 NMF candidates, then re-score with a blended
    objective: 70% relevance rank + 30% cost savings.
    """
    from src.recommender import _load_artifacts, _nmf as nmf_model

    _load_artifacts()
    costs = _load_movie_costs()

    if not base_recs or not costs:
        return base_recs

    # Expand candidate pool with top-40 NMF scores if available
    candidates = list(base_recs)
    if nmf_model:
        user_idx = nmf_model.get("user_id_to_idx", {})
        if str(user_id) in user_idx:
            W = nmf_model["W"]
            H = nmf_model["H"]
            idx_to_mid = nmf_model["idx_to_movie_id"]
            u = user_idx[str(user_id)]
            scores = W[u] @ H
            top_idx = np.argsort(-scores)[:40]
            for i in top_idx:
                mid = idx_to_mid.get(i)
                if mid and mid not in candidates:
                    candidates.append(mid)

    # Compute max cost for normalisation
    candidate_costs = [costs.get(mid, 0.0) for mid in candidates]
    max_cost = max(candidate_costs) if candidate_costs else 1.0
    if max_cost == 0:
        max_cost = 1.0

    # Blend: relevance rank score (higher = better) + cost savings
    scored = []
    n = len(candidates)
    for rank, mid in enumerate(candidates):
        relevance_score = 1.0 - (rank / max(n, 1))
        cost = costs.get(mid, 0.0)
        cost_savings = 1.0 - (cost / max_cost)
        blended = 0.70 * relevance_score + 0.30 * cost_savings
        scored.append((mid, blended))

    scored.sort(key=lambda x: x[1], reverse=True)
    return [mid for mid, _ in scored[:20]]


def recommend_cost_optimised(user_id, user_data=None, **kwargs):
    """
    Treatment: Re-rank standard recommendations to prefer cheaper movies.
    Calls get_recommendations internally; used when exp_cost_optimise runs standalone.
    """
    from src.recommender import get_recommendations
    base_recs = get_recommendations(user_id, user_data=user_data, force_popularity=False)
    return _apply_cost_rerank(user_id, base_recs)


# ---------------------------------------------------------------------------
# Variant registry: maps (experiment_id, variant_name) -> function
# ---------------------------------------------------------------------------

VARIANT_FUNCTIONS = {
    # Experiment 1: cold-start impact
    ("exp_cold_start", "control"): recommend_with_cold_start,
    ("exp_cold_start", "no_cold_start"): recommend_without_cold_start,
    # Experiment 2: cost optimisation
    ("exp_cost_optimise", "control"): recommend_standard,
    ("exp_cost_optimise", "cost_optimised"): recommend_cost_optimised,
}


def get_variant_recommender(experiment_id: str, variant_name: str):
    """Return the recommendation function for a given experiment variant."""
    return VARIANT_FUNCTIONS.get((experiment_id, variant_name))
