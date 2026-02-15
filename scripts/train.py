#!/usr/bin/env python3
"""
Train two recommendation models for Milestone 1:
  Model A: Collaborative filtering (NMF)
  Model B: Content-based popularity + genre matching

Saves models and artifacts to models/ for serving.
"""
import json
import os
import re
import time
import pandas as pd
import numpy as np
from scipy.sparse import csr_matrix
from sklearn.decomposition import NMF
from sklearn.preprocessing import LabelEncoder
import joblib

# Paths (run from project root)
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(PROJECT_ROOT, "data", "processed")
METADATA_DIR = os.path.join(PROJECT_ROOT, "metadata")
MODELS_DIR = os.path.join(PROJECT_ROOT, "models")
os.makedirs(MODELS_DIR, exist_ok=True)


def load_data():
    """Load ratings, watches, movies, and users."""
    ratings = pd.read_csv(os.path.join(DATA_DIR, "ratings.csv"))
    watches = pd.read_csv(os.path.join(DATA_DIR, "watches.csv"))
    with open(os.path.join(METADATA_DIR, "movies.json")) as f:
        movies = json.load(f)
    with open(os.path.join(METADATA_DIR, "users.json")) as f:
        users = json.load(f)
    return ratings, watches, movies, users


def build_title_to_movie_id(movies):
    """Build mapping from normalized title to movie_id for cold-start matching."""
    title_to_id = {}
    for mid, m in movies.items():
        if not isinstance(m, dict):
            continue
        title = m.get("title") or m.get("original_title") or ""
        if not title:
            continue
        # Normalize: lowercase, replace spaces/special with +
        normalized = re.sub(r"[^\w]", "+", title.lower()).strip("+")
        normalized = re.sub(r"\++", "+", normalized)
        if normalized and mid not in title_to_id:
            title_to_id[normalized] = mid
        # Also add movie id as self-key for exact match
        if mid:
            title_to_id[mid.lower().replace(" ", "+")] = mid
    return title_to_id


def extract_movies_from_description(text, title_to_id):
    """Parse self_description_likes/dislikes and match movie titles."""
    if not text or not isinstance(text, str) or not text.strip():
        return []
    found = []
    text_lower = text.lower()
    # Common patterns: 'Movie Title', "Movie Title", Movie Title
    for norm, mid in title_to_id.items():
        # Simple heuristic: if the normalized form appears in text
        search = norm.replace("+", " ")
        if search in text_lower or norm.replace("+", "") in text_lower.replace(" ", ""):
            found.append(mid)
    return list(set(found))[:20]  # Cap at 20


# --- Model A: NMF (Collaborative Filtering) ---
def train_nmf(ratings, movies):
    """Train NMF on user-item rating matrix."""
    # Filter to movies in catalog
    valid_movies = set(movies.keys())
    r = ratings[ratings["movie_id"].isin(valid_movies)].copy()
    r = r[r["rating"] >= 1]
    r = r[r["rating"] <= 5]

    user_enc = LabelEncoder()
    movie_enc = LabelEncoder()
    r["user_idx"] = user_enc.fit_transform(r["user_id"].astype(str))
    r["movie_idx"] = movie_enc.fit_transform(r["movie_id"].astype(str))

    n_users = r["user_idx"].max() + 1
    n_movies = r["movie_idx"].max() + 1
    matrix = csr_matrix(
        (r["rating"].values, (r["user_idx"].values, r["movie_idx"].values)),
        shape=(n_users, n_movies),
    )

    start = time.time()
    model = NMF(n_components=50, init="nndsvda", random_state=42, max_iter=200)
    W = model.fit_transform(matrix)
    H = model.components_
    train_time = time.time() - start

    # Inverse mappings
    user_id_to_idx = {str(uid): i for i, uid in enumerate(user_enc.classes_)}
    idx_to_movie_id = {i: mid for i, mid in enumerate(movie_enc.classes_)}
    all_movie_ids = list(movie_enc.classes_)

    return {
        "model": model,
        "W": W,
        "H": H,
        "user_id_to_idx": user_id_to_idx,
        "idx_to_movie_id": idx_to_movie_id,
        "all_movie_ids": all_movie_ids,
        "n_movies": n_movies,
        "train_time_sec": train_time,
    }


# --- Model B: Popularity + Genre (Content-based) ---
def train_popularity(ratings, watches, movies):
    """Build popularity scores and genre index."""
    # Movie popularity: weighted by rating and count
    agg = ratings.groupby("movie_id").agg(
        mean_rating=("rating", "mean"),
        count_rating=("rating", "count"),
    )
    watch_counts = watches.groupby("movie_id")["minutes_watched"].sum()
    agg = agg.join(watch_counts, how="outer").fillna(0)
    # Score = count * (mean_rating - 2.5) to favor highly rated; add small prior
    agg["score"] = (agg["count_rating"] + 1) * (agg["mean_rating"].fillna(3) - 2) + 1
    popularity_rank = agg["score"].sort_values(ascending=False)
    top_movies = popularity_rank.index.tolist()

    # Genre per movie
    genre_to_movies = {}
    for mid, m in movies.items():
        if not isinstance(m, dict):
            continue
        genres = m.get("genres") or []
        if isinstance(genres, list):
            for g in genres:
                name = g.get("name") if isinstance(g, dict) else str(g)
                if name:
                    genre_to_movies.setdefault(name, []).append(mid)

    # Build title mapping for cold start
    title_to_id = build_title_to_movie_id(movies)

    return {
        "top_movies": top_movies,
        "popularity_scores": popularity_rank.to_dict(),
        "genre_to_movies": genre_to_movies,
        "title_to_id": title_to_id,
        "movies": movies,
        "train_time_sec": 0.0,  # No training, just aggregation
    }


def main():
    print("Loading data...")
    ratings, watches, movies, users = load_data()
    print(f"  Ratings: {len(ratings)}, Watches: {len(watches)}")
    print(f"  Movies: {len(movies)}, Users: {len(users)}")

    # Train Model A: NMF
    print("\n--- Model A: NMF (Collaborative Filtering) ---")
    nmf_artifacts = train_nmf(ratings, movies)
    path_a = os.path.join(MODELS_DIR, "model_nmf.joblib")
    joblib.dump(nmf_artifacts, path_a)
    print(f"  Saved to {path_a} (train time: {nmf_artifacts['train_time_sec']:.1f}s)")

    # Train Model B: Popularity
    print("\n--- Model B: Popularity + Genre ---")
    pop_artifacts = train_popularity(ratings, watches, movies)
    path_b = os.path.join(MODELS_DIR, "model_popularity.joblib")
    joblib.dump(pop_artifacts, path_b)
    print(f"  Saved to {path_b}")

    # Save cold-start helper (title_to_id) for both - app will use it
    cold_start = {
        "title_to_id": pop_artifacts["title_to_id"],
        "extract_movies_from_description": None,  # function; we'll use logic in app
    }
    cs_path = os.path.join(MODELS_DIR, "cold_start.joblib")
    joblib.dump(
        {
            "title_to_id": pop_artifacts["title_to_id"],
            "top_movies": pop_artifacts["top_movies"][:500],
        },
        cs_path,
    )
    print(f"  Cold-start artifacts: {cs_path}")

    print("\nTraining complete.")


if __name__ == "__main__":
    main()
