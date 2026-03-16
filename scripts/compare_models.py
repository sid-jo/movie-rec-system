#!/usr/bin/env python3
"""
Model comparison for Milestone 1: Measure 4 qualities for both models.
  (1) Prediction accuracy (RMSE on held-out ratings)
  (2) Training cost (wall-clock seconds)
  (3) Inference cost (throughput req/s, median latency ms)
  (4) Model size (disk MB)
"""
import os
import time
import json
import pandas as pd
import numpy as np
import joblib
from sklearn.model_selection import train_test_split
from sklearn.metrics import mean_squared_error

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(PROJECT_ROOT, "data", "processed")
MODELS_DIR = os.path.join(PROJECT_ROOT, "models")
METADATA_DIR = os.path.join(PROJECT_ROOT, "metadata")


def load_models():
    nmf_path = os.path.join(MODELS_DIR, "model_nmf.joblib")
    pop_path = os.path.join(MODELS_DIR, "model_popularity.joblib")
    if not os.path.exists(nmf_path) or not os.path.exists(pop_path):
        raise FileNotFoundError("Run scripts/train.py first")
    return joblib.load(nmf_path), joblib.load(pop_path)


# --- 1. Prediction Accuracy ---
def metric_accuracy():
    """Metric: RMSE between predicted and actual ratings on held-out test set."""
    ratings = pd.read_csv(os.path.join(DATA_DIR, "ratings.csv"))
    with open(os.path.join(METADATA_DIR, "movies.json")) as f:
        movies = json.load(f)
    valid = set(movies.keys())
    r = ratings[ratings["movie_id"].isin(valid)]
    train_df, test_df = train_test_split(r, test_size=0.2, random_state=42)

    nmf, pop = load_models()

    # NMF: predict for test user-movie pairs
    nmf_errors = []
    user_idx = nmf["user_id_to_idx"]
    idx_to_mid = nmf["idx_to_movie_id"]
    mid_to_idx = {v: k for k, v in idx_to_mid.items()}
    W, H = nmf["W"], nmf["H"]
    for _, row in test_df.iterrows():
        uid, mid = str(row["user_id"]), row["movie_id"]
        if uid not in user_idx or mid not in mid_to_idx:
            continue
        u = user_idx[uid]
        m = mid_to_idx[mid]
        pred = np.dot(W[u], H[:, m])
        pred = np.clip(pred, 1, 5)
        nmf_errors.append((pred - row["rating"]) ** 2)
    rmse_nmf = np.sqrt(np.mean(nmf_errors)) if nmf_errors else float("nan")

    # Popularity: no direct rating predictor; use mean rating as proxy (content model)
    # For content model we don't predict ratings - we rank. Use a proxy: RMSE of mean movie rating
    agg = train_df.groupby("movie_id")["rating"].mean()
    pop_errors = []
    for _, row in test_df.iterrows():
        mid = row["movie_id"]
        pred = agg.get(mid, 3.0)
        pop_errors.append((pred - row["rating"]) ** 2)
    rmse_pop = np.sqrt(np.mean(pop_errors)) if pop_errors else float("nan")

    return {"NMF": rmse_nmf, "Popularity": rmse_pop}


# --- 2. Training Cost ---
def metric_training_cost():
    """Metric: Wall-clock time in seconds to train each model."""
    nmf, pop = load_models()
    return {
        "NMF": nmf.get("train_time_sec", float("nan")),
        "Popularity": pop.get("train_time_sec", 0.0),
    }


# --- 3. Inference Cost ---
def metric_inference_cost():
    """Metric: Throughput (req/s) and median latency (ms) for 1000 recommendation requests per model."""
    import sys
    sys.path.insert(0, PROJECT_ROOT)
    from src.recommender import get_recommendations

    nmf, pop = load_models()
    nmf_users = list(nmf["user_id_to_idx"].keys()) * (1000 // max(1, len(nmf["user_id_to_idx"])) + 1)
    any_users = nmf_users[:1000]  # Same 1000 user IDs for both

    # NMF path (known users)
    lat_nmf = []
    for uid in any_users[:1000]:
        t0 = time.perf_counter()
        get_recommendations(uid, force_popularity=False)
        lat_nmf.append((time.perf_counter() - t0) * 1000)
    lat_nmf = np.array(lat_nmf)

    # Popularity path
    lat_pop = []
    for uid in any_users[:1000]:
        t0 = time.perf_counter()
        get_recommendations(uid, force_popularity=True)
        lat_pop.append((time.perf_counter() - t0) * 1000)
    lat_pop = np.array(lat_pop)

    return {
        "NMF": {"median_ms": np.median(lat_nmf), "req_per_s": 1000.0 / (np.sum(lat_nmf) / 1000)},
        "Popularity": {"median_ms": np.median(lat_pop), "req_per_s": 1000.0 / (np.sum(lat_pop) / 1000)},
    }


# --- 4. Model Size ---
def metric_model_size():
    """Metric: Disk size in MB of serialized model files."""
    nmf_path = os.path.join(MODELS_DIR, "model_nmf.joblib")
    pop_path = os.path.join(MODELS_DIR, "model_popularity.joblib")
    return {
        "NMF": os.path.getsize(nmf_path) / (1024 * 1024),
        "Popularity": os.path.getsize(pop_path) / (1024 * 1024),
    }


def main():
    print("=" * 60)
    print("Model Comparison (4 Qualities)")
    print("=" * 60)

    print("\n1. Prediction Accuracy (RMSE on held-out ratings)")
    acc = metric_accuracy()
    print(f"   NMF:        {acc['NMF']:.4f}")
    print(f"   Popularity: {acc['Popularity']:.4f}")

    print("\n2. Training Cost (seconds)")
    tc = metric_training_cost()
    print(f"   NMF:        {tc['NMF']:.2f}s")
    print(f"   Popularity: {tc['Popularity']:.2f}s")

    print("\n3. Inference Cost (median latency ms / throughput req/s)")
    inf = metric_inference_cost()
    print(f"   NMF:        {inf['NMF']['median_ms']:.2f} ms, {inf['NMF']['req_per_s']:.1f} req/s")
    print(f"   Popularity: {inf['Popularity']['median_ms']:.2f} ms, {inf['Popularity']['req_per_s']:.1f} req/s")

    print("\n4. Model Size (MB)")
    sz = metric_model_size()
    print(f"   NMF:        {sz['NMF']:.3f} MB")
    print(f"   Popularity: {sz['Popularity']:.3f} MB")

    # Table
    print("\n" + "=" * 60)
    print("Summary Table")
    print("=" * 60)
    table = pd.DataFrame({
        "NMF": [acc["NMF"], tc["NMF"], f"{inf['NMF']['median_ms']:.1f} ms", f"{sz['NMF']:.3f} MB"],
        "Popularity": [acc["Popularity"], tc["Popularity"], f"{inf['Popularity']['median_ms']:.1f} ms", f"{sz['Popularity']:.3f} MB"],
    }, index=["Accuracy (RMSE)", "Training (s)", "Inference (median latency)", "Size (MB)"])
    print(table.to_string())
    print("=" * 60)


if __name__ == "__main__":
    main()


# --- Offline eval entry point (writes evaluation_results.json) ---
def run_offline_eval_and_save():
    """Run evaluation and save to evaluation_results.json."""
    acc = metric_accuracy()
    tc = metric_training_cost()
    inf = metric_inference_cost()
    sz = metric_model_size()
    results = {
        "accuracy_rmse": acc,
        "training_cost": tc,
        "inference_cost": inf,
        "model_size_mb": sz,
    }
    out_path = os.path.join(PROJECT_ROOT, "evaluation_results.json")
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2)
    return out_path
