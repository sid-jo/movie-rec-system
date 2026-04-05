#!/usr/bin/env python3
"""
Experiment Analysis: compute per-variant metrics and statistical significance.

Reads experiment assignment logs and correlates with Kafka telemetry (watch /
rating events) to compare variant outcomes.  Reports:

  - Watch-Through Rate (WTR) per variant
  - Positive-Rating Rate (PRR) per variant
  - Average rating per variant
  - Average licensing cost per variant
  - Two-proportion z-test (WTR, PRR) and Welch's t-test (ratings, cost)
  - 95% confidence intervals for each metric

Usage:
  python scripts/experiment_analysis.py --experiment exp_cold_start
  python scripts/experiment_analysis.py --experiment exp_cost_optimise
  python scripts/experiment_analysis.py --all
"""
import argparse
import json
import math
import os
import sys
from collections import defaultdict
from datetime import datetime

import numpy as np

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

EXPERIMENTS_DIR = os.path.join(PROJECT_ROOT, "experiments")
LOG_DIR = os.path.join(EXPERIMENTS_DIR, "logs")
METADATA_DIR = os.path.join(PROJECT_ROOT, "metadata")
RESULTS_DIR = os.path.join(EXPERIMENTS_DIR, "results")
# Also check for Kafka-sourced telemetry
TELEMETRY_DIR = os.path.join(PROJECT_ROOT, "data", "raw_logs")

POSITIVE_RATING_THRESHOLD = 4.0


# ---------------------------------------------------------------------------
# Statistical tests
# ---------------------------------------------------------------------------

def two_proportion_z_test(successes_a, n_a, successes_b, n_b):
    """
    Two-proportion z-test for comparing rates between two groups.

    H0: p_a == p_b
    Returns z-statistic and two-sided p-value.
    """
    if n_a == 0 or n_b == 0:
        return 0.0, 1.0

    p_a = successes_a / n_a
    p_b = successes_b / n_b
    p_pool = (successes_a + successes_b) / (n_a + n_b)

    if p_pool == 0 or p_pool == 1:
        return 0.0, 1.0

    se = math.sqrt(p_pool * (1 - p_pool) * (1 / n_a + 1 / n_b))
    if se == 0:
        return 0.0, 1.0

    z = (p_a - p_b) / se
    # Two-sided p-value using normal approximation
    p_value = 2 * (1 - _norm_cdf(abs(z)))
    return z, p_value


def welch_t_test(values_a, values_b):
    """
    Welch's t-test for comparing means of two groups with unequal variances.

    H0: mean_a == mean_b
    Returns t-statistic and two-sided p-value.
    """
    n_a, n_b = len(values_a), len(values_b)
    if n_a < 2 or n_b < 2:
        return 0.0, 1.0

    mean_a, mean_b = np.mean(values_a), np.mean(values_b)
    var_a, var_b = np.var(values_a, ddof=1), np.var(values_b, ddof=1)

    se = math.sqrt(var_a / n_a + var_b / n_b)
    if se == 0:
        return 0.0, 1.0

    t = (mean_a - mean_b) / se

    # Welch-Satterthwaite degrees of freedom
    num = (var_a / n_a + var_b / n_b) ** 2
    denom = ((var_a / n_a) ** 2 / (n_a - 1)) + ((var_b / n_b) ** 2 / (n_b - 1))
    if denom == 0:
        return 0.0, 1.0
    df = num / denom

    # Approximate p-value using t-distribution via normal for large df
    p_value = 2 * (1 - _t_cdf(abs(t), df))
    return t, p_value


def _norm_cdf(x):
    """Standard normal CDF (no scipy dependency)."""
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def _t_cdf(t, df):
    """Approximate t-distribution CDF using normal approximation for df > 30,
    otherwise use a simple Cornish-Fisher expansion."""
    if df > 30:
        return _norm_cdf(t)
    # For smaller df, use a rough beta-based approximation
    x = df / (df + t * t)
    # Regularised incomplete beta function approximation
    a, b = df / 2.0, 0.5
    return 1 - 0.5 * _beta_inc_approx(a, b, x)


def _beta_inc_approx(a, b, x):
    """Very rough regularised incomplete beta via continued fraction (8 terms)."""
    if x <= 0:
        return 0.0
    if x >= 1:
        return 1.0
    # Use simple series for small a,b
    result = (x ** a) * ((1 - x) ** b) / a
    term = result
    for n in range(1, 50):
        term *= (a + n - 1) * x / (a + n)
        result += term
        if abs(term) < 1e-12:
            break
    # Normalise by beta function B(a,b)
    log_beta = math.lgamma(a) + math.lgamma(b) - math.lgamma(a + b)
    return min(max(result / math.exp(log_beta), 0), 1)


def confidence_interval_proportion(successes, n, z=1.96):
    """95% CI for a proportion using Wald interval."""
    if n == 0:
        return 0.0, 0.0, 0.0
    p = successes / n
    se = math.sqrt(p * (1 - p) / n) if n > 0 else 0
    return p, max(0, p - z * se), min(1, p + z * se)


def confidence_interval_mean(values, z=1.96):
    """95% CI for a mean."""
    if len(values) == 0:
        return 0.0, 0.0, 0.0
    mean = np.mean(values)
    se = np.std(values, ddof=1) / math.sqrt(len(values)) if len(values) > 1 else 0
    return float(mean), float(mean - z * se), float(mean + z * se)


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def load_experiment_log(experiment_id):
    """Load JSONL assignment logs for an experiment."""
    log_path = os.path.join(LOG_DIR, f"{experiment_id}.jsonl")
    if not os.path.exists(log_path):
        print(f"No log file found at {log_path}")
        return []
    records = []
    with open(log_path) as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return records


def load_movie_metadata():
    path = os.path.join(METADATA_DIR, "movies.json")
    if not os.path.exists(path):
        return {}
    with open(path) as f:
        return json.load(f)


def load_telemetry_events():
    """Load watch and rating events from raw telemetry logs or processed data."""
    watches = {}   # (user_id, movie_id) -> minutes
    ratings = {}   # (user_id, movie_id) -> rating

    # Try processed CSVs first
    import csv
    ratings_path = os.path.join(PROJECT_ROOT, "data", "processed", "ratings.csv")
    watches_path = os.path.join(PROJECT_ROOT, "data", "processed", "watches.csv")

    if os.path.exists(ratings_path):
        with open(ratings_path) as f:
            reader = csv.DictReader(f)
            for row in reader:
                uid = row.get("user_id", "")
                mid = row.get("movie_id", "")
                r = float(row.get("rating", 0))
                if uid and mid:
                    ratings[(uid, mid)] = r

    if os.path.exists(watches_path):
        with open(watches_path) as f:
            reader = csv.DictReader(f)
            for row in reader:
                uid = row.get("user_id", "")
                mid = row.get("movie_id", "")
                mins = int(row.get("minutes_watched", 0))
                if uid and mid:
                    watches[(uid, mid)] = mins

    return watches, ratings


# ---------------------------------------------------------------------------
# Per-variant metric computation
# ---------------------------------------------------------------------------

def compute_variant_metrics(records, watches, ratings, movie_metadata):
    """
    Compute per-variant metrics from experiment assignment logs.

    For each variant, calculate:
      - WTR: fraction of recommended movies the user actually watched
      - PRR: fraction of recommended movies rated >= threshold
      - avg_rating: mean rating of recommended movies that were rated
      - avg_cost: mean license cost of recommended movies that were watched
    """
    variant_data = defaultdict(lambda: {
        "users": set(),
        "total_recs": 0,
        "watched_hits": 0,
        "positive_rated_hits": 0,
        "all_ratings": [],
        "all_costs": [],
        "rec_costs": [],      # cost of movies recommended (whether watched or not)
    })

    for record in records:
        variant = record.get("variant", "unknown")
        uid = str(record.get("user_id", ""))
        recs = record.get("recommendations", [])

        vd = variant_data[variant]
        vd["users"].add(uid)
        vd["total_recs"] += len(recs)

        for mid in recs:
            # Check if user watched this recommended movie
            if (uid, mid) in watches:
                vd["watched_hits"] += 1
                # Get license cost for watched recommendations
                movie_info = movie_metadata.get(mid, {})
                cost = 0.0
                if isinstance(movie_info, dict):
                    cost = movie_info.get("license_cost") or movie_info.get("cost") or 0.0
                    try:
                        cost = float(cost)
                    except (ValueError, TypeError):
                        cost = 0.0
                vd["all_costs"].append(cost)

            # Check rating
            if (uid, mid) in ratings:
                r = ratings[(uid, mid)]
                vd["all_ratings"].append(r)
                if r >= POSITIVE_RATING_THRESHOLD:
                    vd["positive_rated_hits"] += 1

            # Track cost of all recommended movies (for cost experiment)
            movie_info = movie_metadata.get(mid, {})
            rec_cost = 0.0
            if isinstance(movie_info, dict):
                rec_cost = movie_info.get("license_cost") or movie_info.get("cost") or 0.0
                try:
                    rec_cost = float(rec_cost)
                except (ValueError, TypeError):
                    rec_cost = 0.0
            vd["rec_costs"].append(rec_cost)

    return variant_data


# ---------------------------------------------------------------------------
# Report generation
# ---------------------------------------------------------------------------

def analyse_experiment(experiment_id, watches, ratings, movie_metadata):
    """Run full analysis for one experiment and print results."""
    records = load_experiment_log(experiment_id)
    if not records:
        print(f"\n  No data for experiment '{experiment_id}'. Run the service to collect data.\n")
        return None

    variant_data = compute_variant_metrics(records, watches, ratings, movie_metadata)
    variant_names = sorted(variant_data.keys())

    print(f"\n{'='*70}")
    print(f"  EXPERIMENT: {experiment_id}")
    print(f"  Records: {len(records)}")
    print(f"{'='*70}\n")

    # Print per-variant summary
    results = {}
    for vname in variant_names:
        vd = variant_data[vname]
        n_users = len(vd["users"])
        total_recs = vd["total_recs"]
        watched = vd["watched_hits"]
        positive = vd["positive_rated_hits"]

        wtr_p, wtr_lo, wtr_hi = confidence_interval_proportion(watched, total_recs)
        prr_p, prr_lo, prr_hi = confidence_interval_proportion(positive, total_recs)
        avg_rating, rat_lo, rat_hi = confidence_interval_mean(vd["all_ratings"])
        avg_cost, cost_lo, cost_hi = confidence_interval_mean(vd["all_costs"])
        avg_rec_cost, rc_lo, rc_hi = confidence_interval_mean(vd["rec_costs"])

        results[vname] = {
            "n_users": n_users,
            "total_recs": total_recs,
            "watched_hits": watched,
            "positive_rated_hits": positive,
            "wtr": wtr_p,
            "prr": prr_p,
            "avg_rating": avg_rating,
            "avg_cost_watched": avg_cost,
            "avg_rec_cost": avg_rec_cost,
            "all_ratings": vd["all_ratings"],
            "all_costs": vd["all_costs"],
            "rec_costs": vd["rec_costs"],
        }

        print(f"  Variant: {vname}")
        print(f"    Users:              {n_users}")
        print(f"    Total recs served:  {total_recs}")
        print(f"    Watch-Through Rate: {wtr_p:.4f}  95% CI [{wtr_lo:.4f}, {wtr_hi:.4f}]")
        print(f"    Positive-Rating:    {prr_p:.4f}  95% CI [{prr_lo:.4f}, {prr_hi:.4f}]")
        print(f"    Avg rating (rated): {avg_rating:.3f}  95% CI [{rat_lo:.3f}, {rat_hi:.3f}]  (n={len(vd['all_ratings'])})")
        print(f"    Avg cost (watched): ${avg_cost:.4f}  95% CI [${cost_lo:.4f}, ${cost_hi:.4f}]  (n={len(vd['all_costs'])})")
        print(f"    Avg rec cost:       ${avg_rec_cost:.4f}  95% CI [${rc_lo:.4f}, ${rc_hi:.4f}]")
        print()

    # Statistical tests between variants
    if len(variant_names) == 2:
        a, b = variant_names[0], variant_names[1]
        ra, rb = results[a], results[b]

        print(f"  --- Statistical Tests: {a} vs {b} ---\n")

        # WTR: two-proportion z-test
        z_wtr, p_wtr = two_proportion_z_test(
            ra["watched_hits"], ra["total_recs"],
            rb["watched_hits"], rb["total_recs"])
        sig_wtr = "YES" if p_wtr < 0.05 else "no"
        print(f"    Watch-Through Rate:")
        print(f"      {a}: {ra['wtr']:.4f}   {b}: {rb['wtr']:.4f}")
        print(f"      z = {z_wtr:.4f}, p = {p_wtr:.6f}  Significant (p<0.05): {sig_wtr}")
        print()

        # PRR: two-proportion z-test
        z_prr, p_prr = two_proportion_z_test(
            ra["positive_rated_hits"], ra["total_recs"],
            rb["positive_rated_hits"], rb["total_recs"])
        sig_prr = "YES" if p_prr < 0.05 else "no"
        print(f"    Positive-Rating Rate:")
        print(f"      {a}: {ra['prr']:.4f}   {b}: {rb['prr']:.4f}")
        print(f"      z = {z_prr:.4f}, p = {p_prr:.6f}  Significant (p<0.05): {sig_prr}")
        print()

        # Rating: Welch's t-test
        t_rat, p_rat = welch_t_test(ra["all_ratings"], rb["all_ratings"])
        sig_rat = "YES" if p_rat < 0.05 else "no"
        print(f"    Average Rating:")
        print(f"      {a}: {ra['avg_rating']:.3f}   {b}: {rb['avg_rating']:.3f}")
        print(f"      t = {t_rat:.4f}, p = {p_rat:.6f}  Significant (p<0.05): {sig_rat}")
        print()

        # Cost: Welch's t-test on recommendation costs
        t_cost, p_cost = welch_t_test(ra["rec_costs"], rb["rec_costs"])
        sig_cost = "YES" if p_cost < 0.05 else "no"
        print(f"    Average Recommendation Cost:")
        print(f"      {a}: ${ra['avg_rec_cost']:.4f}   {b}: ${rb['avg_rec_cost']:.4f}")
        print(f"      t = {t_cost:.4f}, p = {p_cost:.6f}  Significant (p<0.05): {sig_cost}")
        print()

        # Save results
        test_results = {
            "experiment_id": experiment_id,
            "analysed_at": datetime.now().isoformat(),
            "records_analysed": len(records),
            "variants": {
                a: {
                    "n_users": ra["n_users"],
                    "total_recs": ra["total_recs"],
                    "wtr": ra["wtr"],
                    "prr": ra["prr"],
                    "avg_rating": ra["avg_rating"],
                    "avg_rec_cost": ra["avg_rec_cost"],
                    "avg_cost_watched": ra["avg_cost_watched"],
                },
                b: {
                    "n_users": rb["n_users"],
                    "total_recs": rb["total_recs"],
                    "wtr": rb["wtr"],
                    "prr": rb["prr"],
                    "avg_rating": rb["avg_rating"],
                    "avg_rec_cost": rb["avg_rec_cost"],
                    "avg_cost_watched": rb["avg_cost_watched"],
                },
            },
            "statistical_tests": {
                "wtr_z_test": {"z": z_wtr, "p_value": p_wtr, "significant": p_wtr < 0.05},
                "prr_z_test": {"z": z_prr, "p_value": p_prr, "significant": p_prr < 0.05},
                "rating_t_test": {"t": t_rat, "p_value": p_rat, "significant": p_rat < 0.05},
                "cost_t_test": {"t": t_cost, "p_value": p_cost, "significant": p_cost < 0.05},
            },
        }

        os.makedirs(RESULTS_DIR, exist_ok=True)
        out_path = os.path.join(RESULTS_DIR, f"{experiment_id}_results.json")
        with open(out_path, "w") as f:
            json.dump(test_results, f, indent=2)
        print(f"  Results saved to {out_path}")

        return test_results

    return results


# ---------------------------------------------------------------------------
# Simulated experiment (for offline analysis / bootstrapping)
# ---------------------------------------------------------------------------

def simulate_experiment(experiment_id, n_users=2000):
    """
    Simulate an experiment by replaying historical data through the variant
    assignment logic.  Useful for generating initial results when the live
    service has not yet accumulated enough traffic.

    Reads processed ratings/watches and assigns each historical user to a
    variant, then evaluates as if those recommendations had been served.
    """
    import csv
    from src.experiment import ExperimentManager, assign_variant

    mgr = ExperimentManager()
    exp = mgr.get_experiment(experiment_id)
    if not exp:
        print(f"Experiment '{experiment_id}' not found.")
        return

    # Load historical user interactions
    ratings_path = os.path.join(PROJECT_ROOT, "data", "processed", "ratings.csv")
    watches_path = os.path.join(PROJECT_ROOT, "data", "processed", "watches.csv")

    if not os.path.exists(ratings_path) or not os.path.exists(watches_path):
        print("Missing processed data files. Run the pipeline first.")
        return

    # Collect unique users with ratings
    user_ratings = defaultdict(dict)  # uid -> {mid: rating}
    with open(ratings_path) as f:
        reader = csv.DictReader(f)
        for row in reader:
            uid = row.get("user_id", "")
            mid = row.get("movie_id", "")
            r = float(row.get("rating", 0))
            if uid and mid:
                user_ratings[uid][mid] = r

    user_watches = defaultdict(set)  # uid -> set of movie_ids
    with open(watches_path) as f:
        reader = csv.DictReader(f)
        for row in reader:
            uid = row.get("user_id", "")
            mid = row.get("movie_id", "")
            if uid and mid:
                user_watches[uid].add(mid)

    # Pick users (those with both ratings and watches for better signal)
    candidate_users = [uid for uid in user_ratings if uid in user_watches]
    if len(candidate_users) > n_users:
        candidate_users = candidate_users[:n_users]

    print(f"Simulating experiment '{experiment_id}' with {len(candidate_users)} users...")

    movie_metadata = load_movie_metadata()
    from src.recommender_variants import get_variant_recommender
    from src.recommender import get_recommendations

    # Generate simulated assignment logs
    simulated_records = []
    for uid in candidate_users:
        variant = assign_variant(exp.id, uid, exp.variants)
        variant_fn = get_variant_recommender(exp.id, variant.name)
        if variant_fn:
            recs = variant_fn(uid, user_data=None)
        else:
            recs = get_recommendations(uid, user_data=None)

        simulated_records.append({
            "experiment_id": exp.id,
            "user_id": uid,
            "variant": variant.name,
            "recommendations": recs[:20] if recs else [],
        })

    # Write simulated log
    os.makedirs(LOG_DIR, exist_ok=True)
    log_path = os.path.join(LOG_DIR, f"{experiment_id}.jsonl")
    with open(log_path, "w") as f:
        for rec in simulated_records:
            f.write(json.dumps(rec) + "\n")
    print(f"  Wrote {len(simulated_records)} simulated records to {log_path}")

    # Convert to the format expected by load_telemetry_events
    watches_dict = {(uid, mid): 1 for uid, mids in user_watches.items() for mid in mids}
    ratings_dict = {(uid, mid): r for uid, mratings in user_ratings.items() for mid, r in mratings.items()}

    return analyse_experiment(experiment_id, watches_dict, ratings_dict, movie_metadata)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Analyse A/B experiment results")
    parser.add_argument("--experiment", "-e", type=str,
                        help="Experiment ID to analyse (e.g. exp_cold_start)")
    parser.add_argument("--all", action="store_true",
                        help="Analyse all experiments with available logs")
    parser.add_argument("--simulate", action="store_true",
                        help="Simulate experiment using historical data")
    parser.add_argument("--n-users", type=int, default=2000,
                        help="Number of users for simulation (default: 2000)")
    args = parser.parse_args()

    if args.simulate and args.experiment:
        simulate_experiment(args.experiment, args.n_users)
        return

    # Load telemetry
    watches, ratings = load_telemetry_events()
    movie_metadata = load_movie_metadata()
    print(f"Loaded telemetry: {len(watches)} watches, {len(ratings)} ratings")
    print(f"Loaded metadata for {len(movie_metadata)} movies")

    if args.experiment:
        analyse_experiment(args.experiment, watches, ratings, movie_metadata)
    elif args.all:
        for fname in sorted(os.listdir(LOG_DIR)):
            if fname.endswith(".jsonl"):
                exp_id = fname.replace(".jsonl", "")
                analyse_experiment(exp_id, watches, ratings, movie_metadata)
    else:
        print("Specify --experiment <id> or --all. Use --simulate to generate data.")
        # List available experiments
        if os.path.exists(EXPERIMENTS_DIR):
            configs = [f.replace(".json", "") for f in os.listdir(EXPERIMENTS_DIR)
                       if f.endswith(".json")]
            if configs:
                print(f"\nAvailable experiments: {', '.join(configs)}")
        if os.path.exists(LOG_DIR):
            logs = [f.replace(".jsonl", "") for f in os.listdir(LOG_DIR)
                    if f.endswith(".jsonl")]
            if logs:
                print(f"Experiments with data: {', '.join(logs)}")


if __name__ == "__main__":
    main()
