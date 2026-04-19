"""
Fairness analysis helpers for the movie recommendation service.

Works on the telemetry we actually have on disk:
  - data/raw_logs/*.jsonl  (watches + ratings, pre-parsed, 34.7M+ events)
  - metadata/users.json     (gender, age, occupation for 46k users)
  - metadata/movies.json    (original_language, budget, adult, genres ...)

Optional hooks for when recommendation-event telemetry is available:
  - a directory of rec-event JSONL files produced by scripts/online_eval.py
    or experiments/logs/exp_*.jsonl (same shape: {user_id, recommendations})

Design notes
------------
* We stream input files; nothing is loaded in full. Aggregates are kept in
  small dicts (max ~46k users or ~10k movies).
* We do not rely on src/kafka_parsing.py — its "recommendation request"
  regex has a double-escape bug (`result: \\[...\\]` only matches a literal
  backslash-bracket which the Kafka logs do not contain). Watches and ratings
  pre-parse fine, which is what we use here.
* Ratings observed on the stream are 1-10 (not 1-5 as the README states).
  Positive-rating default threshold is therefore >= 7.
"""
from __future__ import annotations

import glob
import json
import math
import os
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Iterable, Iterator

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
AGE_BUCKETS = [
    (0, 18, "<18"),
    (18, 26, "18-25"),
    (26, 41, "26-40"),
    (41, 61, "41-60"),
    (61, 200, "60+"),
]

POSITIVE_RATING = 7  # on the observed 1-10 scale
MIN_WATCH_MINUTE = 5  # minute number >= this counts as "engaged watch"

_REC_LIST_RE = re.compile(r"result: \[?(.*)")
_WATCH_RAW_RE = re.compile(r"/data/m/([^/]+)/(\d+)\.mpg")
_RATE_RAW_RE = re.compile(r"/rate/(.+)=(\d+)")


# ---------------------------------------------------------------------------
# Loaders
# ---------------------------------------------------------------------------
def load_users(path: str = "metadata/users.json") -> dict:
    with open(path) as f:
        return json.load(f)


def load_movies(path: str = "metadata/movies.json") -> dict:
    with open(path) as f:
        return json.load(f)


def iter_watch_rating_events(log_dir: str, max_files: int | None = None) -> Iterator[dict]:
    """Stream watch/rating events from pre-parsed JSONL shards.

    Yields dicts with keys:
      type: 'watch'  -> {userid, movieid, minute, timestamp}
      type: 'rating' -> {userid, movieid, rating, timestamp}
    """
    files = sorted(glob.glob(os.path.join(log_dir, "*.jsonl")))
    if max_files:
        files = files[:max_files]
    for p in files:
        with open(p) as f:
            for line in f:
                try:
                    obj = json.loads(line)
                except Exception:
                    continue
                t = obj.get("type")
                if t not in ("watch", "rating"):
                    continue
                yield obj


def iter_rec_events(rec_log_dir: str) -> Iterator[dict]:
    """Stream recommendation events from a directory of JSONL files.

    Accepts either:
      (a) raw Kafka JSONL where each line has a 'raw' field holding a log line
          that we need to re-parse with the correct regex;
      (b) experiments/logs/*.jsonl shape already containing 'user_id' +
          'recommendations' list.
    """
    files = sorted(glob.glob(os.path.join(rec_log_dir, "*.jsonl")))
    for p in files:
        with open(p) as f:
            for line in f:
                try:
                    obj = json.loads(line)
                except Exception:
                    continue
                # case (b): experiment assignment log
                if "recommendations" in obj and isinstance(obj["recommendations"], list):
                    yield {
                        "userid": str(obj.get("user_id") or obj.get("userid") or ""),
                        "timestamp": obj.get("timestamp", ""),
                        "rec_list": [str(m) for m in obj["recommendations"]],
                    }
                    continue
                # case (a): raw Kafka line — parse the 'raw' field
                raw = obj.get("raw", "")
                if "recommendation request" not in raw:
                    continue
                parts = raw.split(",", 2)
                if len(parts) < 3:
                    continue
                ts, uid, action = parts
                status_m = re.search(r"status (\d+)", action)
                if not status_m or int(status_m.group(1)) != 200:
                    continue
                m = _REC_LIST_RE.search(action)
                if not m:
                    continue
                rec_str = m.group(1).rstrip("]").strip()
                rec_list = [x.strip().strip("'\" ") for x in rec_str.split(",") if x.strip()]
                if rec_list:
                    yield {"userid": uid, "timestamp": ts, "rec_list": rec_list}


# ---------------------------------------------------------------------------
# Grouping
# ---------------------------------------------------------------------------
def age_bucket(age) -> str:
    try:
        age_i = int(age)
    except (TypeError, ValueError):
        return "unknown"
    for lo, hi, lbl in AGE_BUCKETS:
        if lo <= age_i < hi:
            return lbl
    return "unknown"


def user_group_map(users: dict, scheme: str) -> dict:
    """scheme in {'gender', 'age', 'occupation'} -> {user_id_str: group_label}."""
    out = {}
    for uid, u in users.items():
        uid_s = str(uid)
        if scheme == "gender":
            out[uid_s] = u.get("gender") or "unknown"
        elif scheme == "age":
            out[uid_s] = age_bucket(u.get("age"))
        elif scheme == "occupation":
            out[uid_s] = u.get("occupation") or "unknown"
        else:
            raise ValueError(f"unknown scheme: {scheme}")
    return out


# ---------------------------------------------------------------------------
# Per-user engagement aggregates (used for R1 proxy)
# ---------------------------------------------------------------------------
@dataclass
class UserAgg:
    watch_count: int = 0        # distinct (movie, minute) watch events
    distinct_movies: int = 0    # computed at the end
    rating_count: int = 0
    rating_sum: int = 0

    @property
    def mean_rating(self) -> float | None:
        return self.rating_sum / self.rating_count if self.rating_count else None


def aggregate_by_user(log_dir: str, max_files: int | None = None) -> dict[str, UserAgg]:
    """Single streaming pass over watch + rating events -> {uid: UserAgg}."""
    per_user: dict[str, UserAgg] = defaultdict(UserAgg)
    movies_seen: dict[str, set] = defaultdict(set)
    for ev in iter_watch_rating_events(log_dir, max_files=max_files):
        uid = str(ev.get("userid", ""))
        if not uid:
            continue
        agg = per_user[uid]
        if ev["type"] == "watch":
            agg.watch_count += 1
            mid = ev.get("movieid")
            if mid:
                movies_seen[uid].add(mid)
        elif ev["type"] == "rating":
            r = ev.get("rating")
            try:
                r_i = int(r)
            except (TypeError, ValueError):
                continue
            agg.rating_count += 1
            agg.rating_sum += r_i
    for uid, agg in per_user.items():
        agg.distinct_movies = len(movies_seen.get(uid, ()))
    return dict(per_user)


# ---------------------------------------------------------------------------
# Group engagement (R1 proxy: no rec events available)
# ---------------------------------------------------------------------------
def group_engagement(
    per_user: dict[str, UserAgg],
    groups: dict[str, str],
) -> dict[str, dict]:
    """Mean per-user watch count and mean rating per group.

    Returns {group: {n_users, mean_watch, ci_watch, mean_rating, ci_rating, rating_n}}.
    CIs are bootstrap 95 % over users within the group.
    """
    by_group: dict[str, list[UserAgg]] = defaultdict(list)
    for uid, agg in per_user.items():
        g = groups.get(uid, "unknown")
        by_group[g].append(agg)

    out = {}
    for g, aggs in by_group.items():
        watches = [a.watch_count for a in aggs]
        ratings = [a.mean_rating for a in aggs if a.mean_rating is not None]
        out[g] = {
            "n_users": len(aggs),
            "mean_watch_per_user": _mean(watches),
            "ci_watch_per_user": _bootstrap_ci(watches),
            "median_watch_per_user": _median(watches),
            "rating_users": len(ratings),
            "mean_rating_per_user": _mean(ratings) if ratings else None,
            "ci_rating_per_user": _bootstrap_ci(ratings) if ratings else (None, None),
        }
    return out


# ---------------------------------------------------------------------------
# Exposure parity (R2: play share vs catalog share)
# ---------------------------------------------------------------------------
def play_counts_by_movie(log_dir: str, max_files: int | None = None) -> Counter:
    """Count watch events (plays) per movie_id across the log corpus."""
    counts: Counter = Counter()
    for ev in iter_watch_rating_events(log_dir, max_files=max_files):
        if ev["type"] == "watch":
            mid = ev.get("movieid")
            if mid:
                counts[mid] += 1
    return counts


def exposure_parity_by_plays(
    play_counts: Counter,
    movies: dict,
    attr: str = "original_language",
    min_catalog: int = 20,
) -> dict:
    """Play share per attribute value vs. its catalog share.

    Returns {value: {catalog_share, play_share, ratio}, ...} plus 'summary'.
    Only values with >= min_catalog catalog titles are scored against the floor.
    """
    # Catalog counts
    cat_counts: Counter = Counter()
    for m in movies.values():
        if isinstance(m, dict):
            cat_counts[m.get(attr)] += 1
    total_cat = sum(cat_counts.values()) or 1

    # Play counts by attribute
    play_by_attr: Counter = Counter()
    for mid, c in play_counts.items():
        meta = movies.get(mid, {}) if isinstance(movies.get(mid, {}), dict) else {}
        play_by_attr[meta.get(attr)] += c
    total_plays = sum(play_by_attr.values()) or 1

    per_value = {}
    eligible_ratios = []
    for val in set(cat_counts) | set(play_by_attr):
        cs = cat_counts[val] / total_cat
        ps = play_by_attr[val] / total_plays
        ratio = (ps / cs) if cs > 0 else None
        per_value[str(val)] = {
            "catalog_count": cat_counts[val],
            "catalog_share": cs,
            "play_count": play_by_attr[val],
            "play_share": ps,
            "ratio": ratio,
        }
        if cat_counts[val] >= min_catalog and ratio is not None:
            eligible_ratios.append((str(val), ratio))

    min_ratio = min((r for _, r in eligible_ratios), default=None)
    return {
        "per_value": per_value,
        "eligible_min_ratio": min_ratio,
        "eligible_languages": sorted(eligible_ratios, key=lambda x: x[1])[:10],
        "attr": attr,
        "min_catalog": min_catalog,
        "total_catalog": total_cat,
        "total_plays": total_plays,
    }


# ---------------------------------------------------------------------------
# Optional: WTR across groups (if rec events are available)
# ---------------------------------------------------------------------------
def watch_through_rate_by_group(
    rec_log_dir: str,
    log_dir: str,
    groups: dict[str, str],
    window_hours: int = 24,
) -> dict:
    """Compute WTR per group when a rec-event directory is provided.

    Simpler than a fully time-windowed join: for each rec event we count a hit
    if the user ever watched any of the recommended movies in the watch corpus
    (lifetime join). This is an upper-bound proxy; tighten with --window-hours
    once timestamps are consistently Z-suffixed across sources.
    """
    # user -> set of movies watched (lifetime)
    watched_by_user: dict[str, set] = defaultdict(set)
    for ev in iter_watch_rating_events(log_dir):
        if ev["type"] == "watch":
            uid = str(ev.get("userid", ""))
            mid = ev.get("movieid")
            if uid and mid:
                watched_by_user[uid].add(mid)

    per_group = defaultdict(lambda: {"rec_slots": 0, "hits": 0, "rec_events": 0})
    for rec in iter_rec_events(rec_log_dir):
        uid = rec["userid"]
        g = groups.get(uid, "unknown")
        w = watched_by_user.get(uid, set())
        rec_list = rec["rec_list"]
        per_group[g]["rec_events"] += 1
        per_group[g]["rec_slots"] += len(rec_list)
        per_group[g]["hits"] += sum(1 for m in rec_list if m in w)

    out = {}
    for g, a in per_group.items():
        n = a["rec_slots"]
        k = a["hits"]
        out[g] = {
            "rec_events": a["rec_events"],
            "rec_slots": n,
            "hits": k,
            "wtr": (k / n) if n else 0.0,
            "wtr_ci": wilson_ci(k, n),
        }
    return out


# ---------------------------------------------------------------------------
# Statistics helpers
# ---------------------------------------------------------------------------
def wilson_ci(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = (z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))) / denom
    return (max(0.0, centre - half), min(1.0, centre + half))


def two_proportion_ztest(k1: int, n1: int, k2: int, n2: int) -> dict | None:
    if not n1 or not n2:
        return None
    p1, p2 = k1 / n1, k2 / n2
    p_pool = (k1 + k2) / (n1 + n2)
    se = math.sqrt(p_pool * (1 - p_pool) * (1 / n1 + 1 / n2))
    if se == 0:
        return None
    z = (p1 - p2) / se
    p_val = 2 * (1 - _std_normal_cdf(abs(z)))
    return {"z": z, "p_value": p_val, "diff": p1 - p2, "p1": p1, "p2": p2}


def welch_ttest(xs: list[float], ys: list[float]) -> dict | None:
    """Welch's t-test on two sample means. Uses normal-approx p-value."""
    if len(xs) < 2 or len(ys) < 2:
        return None
    m1, m2 = _mean(xs), _mean(ys)
    v1, v2 = _var(xs), _var(ys)
    n1, n2 = len(xs), len(ys)
    se = math.sqrt(v1 / n1 + v2 / n2)
    if se == 0:
        return None
    t = (m1 - m2) / se
    p_val = 2 * (1 - _std_normal_cdf(abs(t)))  # large-N approximation
    return {"t": t, "p_value": p_val, "diff": m1 - m2, "mean1": m1, "mean2": m2, "n1": n1, "n2": n2}


def _std_normal_cdf(x: float) -> float:
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def _mean(xs):
    return sum(xs) / len(xs) if xs else 0.0


def _var(xs):
    if len(xs) < 2:
        return 0.0
    m = _mean(xs)
    return sum((x - m) ** 2 for x in xs) / (len(xs) - 1)


def _median(xs):
    if not xs:
        return 0.0
    s = sorted(xs)
    n = len(s)
    if n % 2:
        return float(s[n // 2])
    return 0.5 * (s[n // 2 - 1] + s[n // 2])


def _bootstrap_ci(xs: list[float], n_iter: int = 500, alpha: float = 0.05) -> tuple[float, float]:
    if not xs:
        return (0.0, 0.0)
    import random
    n = len(xs)
    means = []
    for _ in range(n_iter):
        sample = [xs[random.randrange(n)] for _ in range(n)]
        means.append(sum(sample) / n)
    means.sort()
    lo = means[int(n_iter * alpha / 2)]
    hi = means[int(n_iter * (1 - alpha / 2))]
    return (lo, hi)


# ---------------------------------------------------------------------------
# Quick data describe (used by the "describe_bias" entry)
# ---------------------------------------------------------------------------
def describe_catalog_bias(movies: dict) -> dict:
    langs = Counter(m.get("original_language") for m in movies.values() if isinstance(m, dict))
    countries = Counter(
        tuple(m.get("origin_country") or ["?"])[0]
        for m in movies.values()
        if isinstance(m, dict)
    )
    budgets = [m.get("budget", 0) or 0 for m in movies.values() if isinstance(m, dict)]
    adults = Counter(bool(m.get("adult")) for m in movies.values() if isinstance(m, dict))
    return {
        "total_titles": len(movies),
        "top_languages": langs.most_common(10),
        "top_countries": countries.most_common(10),
        "budget_zero_share": (sum(1 for b in budgets if not b) / len(budgets)) if budgets else 0.0,
        "adult_counts": dict(adults),
    }


def describe_user_bias(users: dict) -> dict:
    gender = Counter(u.get("gender") for u in users.values())
    ages = [u.get("age") for u in users.values() if isinstance(u.get("age"), (int, float))]
    buckets = Counter(age_bucket(a) for a in ages)
    occupations = Counter(u.get("occupation") for u in users.values())
    return {
        "total_users": len(users),
        "gender_counts": dict(gender),
        "age_bucket_counts": dict(buckets),
        "top_occupations": occupations.most_common(10),
    }
