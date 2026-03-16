# Milestone 2 Report: Model and Infrastructure Quality

## 1. Offline Evaluation

**Validation/test split:** We use a user-based holdout. Users with at least 10 ratings are eligible; we sample up to 200 test users. For each test user, we treat movies rated 7+ (on the 1–10 scale) as "relevant" items.

**Metric (3-step description):**
1. **Definition:** NDCG@20 (Normalized Discounted Cumulative Gain at rank 20) measures the ranking quality of the top-20 recommendations.
2. **Operationalization:** For each test user, we generate top-20 recommendations, compute DCG as the sum of (relevance / log2(position+1)) for relevant items in the list, normalize by the ideal DCG, and average across users.
3. **Justification:** NDCG@20 is suitable for recommendation because it rewards placing relevant items higher in the list and is standard for ranking evaluation.

**Pitfalls avoided:** (1) No label leakage—holdout users' test ratings are never used for training. (2) Temporal/user split reduces data dependence. (3) Single evaluation run to avoid test-set overfitting.

**Implementation:** [scripts/compare_models.py](scripts/compare_models.py), [scripts/offline_eval.py](scripts/offline_eval.py). Run `python scripts/offline_eval.py` to produce [evaluation_results.json](evaluation_results.json).

---

## 2. Online Evaluation

**Accuracy metric (3-step):**
1. **Metric:** Fraction of recommendations that lead to a watch (implicit positive), or mean reciprocal rank of first watched movie in recommendations.
2. **Telemetry:** Each `/recommend/<userid>` response is logged with userid, recommendations list, latency_ms, and timestamp to [logs/telemetry.jsonl](logs/telemetry.jsonl).
3. **Operationalization:** Telemetry is joined with Kafka watch events; we compute the fraction of recommendation sessions where the user watched at least one recommended movie within 7 days.

**Cost metric (3-step):**
1. **Metric:** Mean license cost per recommendation (USD), summed from movie metadata `cost` field.
2. **Telemetry:** Same telemetry records; we add `movie_license_cost_usd` per request.
3. **Operationalization:** Sum `movie_license_cost_usd` across requests and divide by request count. LLM token usage is logged if present.

**Implementation:** [src/telemetry.py](src/telemetry.py), [src/app.py](src/app.py) (integrated).

---

## 3. Data Quality

**Schema enforcement:**
- **Kafka/raw logs:** [pipeline/data_quality.py](pipeline/data_quality.py) `validate_kafka_event()` checks required fields (type, userid, movieid, rating, etc.) per event type. Invalid events are counted and optionally written to `data/quality/invalid_events.jsonl`.
- **User API:** `validate_user_api_response()` ensures userid and optional string fields.
- **Movie API:** `validate_movie_api_response()` ensures id/title and optional numeric cost.
- **Recommendation API:** `validate_userid()` rejects empty, oversized, or injection-prone inputs.

**Drift detection:**
- **Rating distribution:** `compute_rating_distribution()` and `detect_rating_drift()` compare L1 distance between baseline and recent rating histograms; flag if above threshold.
- **Feature drift:** `compute_feature_stats()` and `detect_feature_drift()` compare mean/std of ratings-per-user and movies-per-user; flag if shift exceeds 3 sigma.
- **Schema drift:** Violation rate is tracked in `run_quality_checks()`; baseline stats can be saved to `data/quality/baseline_stats.json`.

**Implementation:** [pipeline/data_quality.py](pipeline/data_quality.py).

---

## 4. Pipeline Implementation and Testing

**Pipeline structure:**
- **pipeline/data_ingest.py:** `parse_log_line()` parses raw Kafka log lines (timestamp,userid,action).
- **pipeline/data_prep.py:** `run()` loads raw logs + metadata, produces ratings.csv, watches.csv, etc.
- **pipeline/train.py:** `run()` trains NMF and popularity models, saves to models/.
- **pipeline/data_quality.py:** Schema validation and drift detection.
- **src/telemetry.py:** Online telemetry logging.

**Testing:** Unit tests in [tests/](tests/) using pytest. Coverage target >70% on pipeline/ and src/.

**Test files:**
- `tests/test_data_ingest.py` – parse_log_line, parse_json_event
- `tests/test_data_prep.py` – data_prep.run with fixtures
- `tests/test_data_quality.py` – validate_kafka_event, drift functions
- `tests/test_train.py` – pipeline.train.run with minimal data
- `tests/test_recommender.py` – get_recommendations format, cold-start, fallback
- `tests/test_app.py` – Flask / and /recommend endpoints

**Adequacy:** Tests cover critical paths (parsing, data prep, validation, training, inference). Mocks/fixtures avoid network and large data. Run: `pytest tests/ -v --cov=pipeline --cov=src --cov-report=html`.

**Coverage report:** Generate with `pytest tests/ --cov=pipeline --cov=src --cov-report=html`; htmlcov/ in project root.

---

## 5. Continuous Integration

**Setup:** GitHub Actions workflow at [.github/workflows/ci.yml](.github/workflows/ci.yml):

- Triggers: push and pull_request on main, master, sai
- Steps: checkout, setup Python 3.12, install requirements + pytest + pytest-cov, create minimal metadata if missing, run tests with coverage

**Access:** GitHub Actions tab on the repository or direct link to workflow runs.

---

## 6. Team Contract

No update to team contract.

---

## 7. Pull Requests (Optional)

If the team uses pull requests and code review, provide a brief description and link to 3 example PRs here.
