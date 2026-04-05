"""
Recommendation logic for the prediction service.
Loads models at import; get_recommendations(user_id) returns list of movie IDs.
"""
import os
import re
import json
import joblib
import numpy as np

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODELS_DIR = os.path.join(PROJECT_ROOT, "models", "artifacts")
METADATA_DIR = os.path.join(PROJECT_ROOT, "metadata")

# Lazy-loaded globals
_nmf = None
_pop = None
_cold_start = None
_valid_movie_ids = None
_top_movies = None
_cold_cache = None
_cold_cache_mtime = 0.0
_COLD_CACHE_PATH = os.path.join(MODELS_DIR, "cold_start_cache.json")


def _get_cold_start_cache():
    """Pre-computed signup cache from scripts/update_cold_start.py (mtime-invalidated)."""
    global _cold_cache, _cold_cache_mtime
    if not os.path.exists(_COLD_CACHE_PATH):
        return {}
    try:
        m = os.path.getmtime(_COLD_CACHE_PATH)
        if _cold_cache is None or m != _cold_cache_mtime:
            with open(_COLD_CACHE_PATH) as f:
                _cold_cache = json.load(f)
            _cold_cache_mtime = m
    except Exception:
        _cold_cache = _cold_cache or {}
    return _cold_cache


def _load_artifacts():
    global _nmf, _pop, _cold_start, _valid_movie_ids, _top_movies
    if _valid_movie_ids is None:
        with open(os.path.join(METADATA_DIR, "movies.json")) as f:
            movies = json.load(f)
        _valid_movie_ids = list(movies.keys())
    if _nmf is None and os.path.exists(os.path.join(MODELS_DIR, "model_nmf.joblib")):
        _nmf = joblib.load(os.path.join(MODELS_DIR, "model_nmf.joblib"))
    if _pop is None and os.path.exists(os.path.join(MODELS_DIR, "model_popularity.joblib")):
        _pop = joblib.load(os.path.join(MODELS_DIR, "model_popularity.joblib"))
    if _cold_start is None and os.path.exists(os.path.join(MODELS_DIR, "cold_start.joblib")):
        _cold_start = joblib.load(os.path.join(MODELS_DIR, "cold_start.joblib"))
    if _top_movies is None and _pop is not None:
        _top_movies = _pop.get("top_movies", [])


def _extract_movies_from_description(text, title_to_id):
    """Match movie titles from self_description text against catalog."""
    if not text or not isinstance(text, str) or not text.strip():
        return []
    found = []
    text_lower = text.lower()
    # Try matching: normalize titles (remove punctuation, collapse spaces)
    for norm_title, mid in title_to_id.items():
        search = norm_title.replace("+", " ")
        # Check if this pattern appears in text (e.g. "the godfather" in "I like The Godfather")
        if search in text_lower:
            found.append(mid)
    return list(dict.fromkeys(found))[:20]


def get_model_type(user_id, user_data=None, force_popularity=False):
    """Return which model path would be used for this user (without computing recs)."""
    _load_artifacts()
    user_id_str = str(user_id)
    cache = _get_cold_start_cache()
    if cache.get(user_id_str, {}).get("recommendations") and not force_popularity:
        return "cold_start_cache"
    if user_data and _cold_start and not force_popularity:
        title_to_id = _cold_start.get("title_to_id", {})
        likes = user_data.get("self_description_likes") or ""
        liked_ids = _extract_movies_from_description(likes, title_to_id)
        if liked_ids:
            return "cold_start"
    if _nmf and not force_popularity:
        if user_id_str in _nmf.get("user_id_to_idx", {}):
            return "nmf"
    if _top_movies:
        return "popularity"
    return "fallback"


def get_recommendations(user_id, user_data=None, force_popularity=False):
    """
    Return up to 20 movie IDs (list) for the user.
    Assignment: "up to 20 movie IDs" — fewer than 20 is fine when format is correct.
    user_data: optional dict from user API (for cold start).
    force_popularity: if True, skip NMF/cold-start and use only popularity (for benchmarking).
    """
    _load_artifacts()
    user_id_str = str(user_id)

    # 0. Signup cache (daemon/cron pre-computed from self-descriptions at signup)
    if not force_popularity:
        cache = _get_cold_start_cache()
        entry = cache.get(user_id_str) or {}
        cached_recs = entry.get("recommendations") or []
        if cached_recs:
            valid = [m for m in cached_recs if m in (_valid_movie_ids or [])]
            if valid:
                return valid[:20]

    # 1. Cold start: use self_description_likes / dislikes if provided
    if user_data and _cold_start and not force_popularity:
        title_to_id = _cold_start.get("title_to_id", {})
        likes = user_data.get("self_description_likes") or ""
        dislikes = user_data.get("self_description_dislikes") or ""
        liked_ids = _extract_movies_from_description(likes, title_to_id)
        disliked_ids = _extract_movies_from_description(dislikes, title_to_id)
        disliked_set = set(disliked_ids)
        # Recommend liked movies first; add similar popular movies
        recs = [m for m in liked_ids if m in _valid_movie_ids][:20]
        if len(recs) < 20:
            for m in _top_movies or []:
                if m not in recs and m not in disliked_set and m in _valid_movie_ids:
                    recs.append(m)
                if len(recs) >= 20:
                    break
        if recs:
            return recs[:20]

    # 2. NMF: known user from training
    if _nmf and not force_popularity:
        user_idx = _nmf.get("user_id_to_idx", {})
        if user_id_str in user_idx:
            W = _nmf["W"]
            H = _nmf["H"]
            idx_to_mid = _nmf["idx_to_movie_id"]
            u = user_idx[user_id_str]
            scores = W[u] @ H
            # Top N unseen (we don't have seen set here; use top by score)
            top_idx = np.argsort(-scores)[:30]
            recs = []
            for i in top_idx:
                mid = idx_to_mid.get(i)
                if mid and mid in _valid_movie_ids:
                    recs.append(mid)
                if len(recs) >= 20:
                    break
            if recs:
                return recs[:20]

    # 3. Fallback: popularity + user-specific variation for personalization
    # Use user_id to seed a deterministic shuffle so different users get different orders
    if _top_movies:
        n = len(_top_movies)
        if n >= 20:
            # Hash user_id to get a starting offset for variety (10% personalized)
            h = hash(user_id_str) % max(1, n - 19)
            recs = _top_movies[h : h + 20]
        else:
            recs = _top_movies[:20]
        valid = [m for m in recs if m in _valid_movie_ids]
        if valid:
            return valid[:20]

    # 4. Last resort: fixed fallback from valid catalog (up to 20)
    fallback = [
        "the+shawshank+redemption+1994",
        "the+godfather+1972",
        "the+dark+knight+2008",
        "pulp+fiction+1994",
        "fight+club+1999",
        "forrest+gump+1994",
        "inception+2010",
        "the+matrix+1999",
        "goodfellas+1990",
        "the+lord+of+the+rings+the+return+of+the+king+2003",
    ]
    return [m for m in fallback if m in _valid_movie_ids][:20]
