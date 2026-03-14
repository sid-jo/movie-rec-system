# Milestone 2 Report: Model and Infrastructure Quality

## Offline Evaluation


### Validation/Test Data

The source data is in `data/processed/ratings.csv`, derived from the production Kafka stream. Each row is a user–movie rating event (1–5 stars) with a timestamp. The dataset contains roughly 210,000 ratings across approximately 1,000,000 users and 20,000 movies.

We apply a **per-user chronological split**: for each user, all rating events are sorted by timestamp and the most recent 20% are held out as the test set, with the remaining 80% forming the training set. This produces a test set of ~42,000 ratings. Splitting within each user (rather than globally by time) ensures every user has at least one test rating.

### Accuracy Metric

**The measure:** For each user in the test set, we measure how well the served recommender ranks movies that the user actually liked (rated ≥ 4.0 out of 5) in their held-out period. Specifically, we measure whether liked movies appear early in a top-20 recommendation list.

**Operationalization with NDCG@20:** We compute the normalized discounted cumulative gain at rank 20. For each user, the relevant set is the collection of movies they rated ≥ 4.0 in their test split. DCG is computed as:

$$\sum_{i=1}^{20} \frac{\mathbf{1}[\text{rec}_i \in \text{relevant}]}{\log_2(i+2)}$$

IDCG is the maximum possible DCG given the number of relevant items. NDCG@20 = DCG / IDCG, normalized to [0, 1]. The final reported metric is the mean NDCG@20 across all evaluated users. We skipped users with no relevant test items and count them separately.

**Justification:** NDCG@20 is a good choice for this problem primarily because our service returns exactly 20 recommendations per request, so $k = 20$ directly matches the output contract. Additionally, it rewards placing liked movies higher in the ranking and normalizes for users with different numbers of liked movies, giving us a standardized measure when comparing across users.

### Avoiding Common Pitfalls

- **Label leakage:** We define "relevant" items using only ratings from the user's test period. No test set rating values are used at training time or to construct features.
- **Data dependence / temporal ordering:** The chronological per-user split ensures that test ratings always come strictly after training ratings for each user, preventing future information from leaking into the training split.
- **Overfitting on test set:** Hyperparameter and model selection decisions were not made by iterating over the test split. We made sure to only use the test split to report final results.

### Evaluation Results

| Model | NDCG@20 | Training Time | Inference Latency (avg) | Model Size |
|-------|---------|---------------|------------------------|------------|
| NMF (Collaborative Filtering) | 0.0568 | 18.82s | 23.05 ms | 4,307 MB |
| Content-Based (Genre) | 0.0137 | 13.79s | 85.10 ms | 3.97 MB |

The NMF model significantly outperforms the content-based model on NDCG@20 (0.057 vs 0.014), confirming that collaborative signals provide stronger personalization. Full results are stored in [`models/artifacts/evaluation_results.json`](https://github.com/cmu-seai/group-project-s26-model-impossible-1/blob/main/models/artifacts/evaluation_results.json).

### Implementation Pointer

- Offline evaluation (NDCG@20, chronological split): [`models/evaluate.py`](https://github.com/cmu-seai/group-project-s26-model-impossible-1/blob/main/models/evaluate.py)
- Model comparison (RMSE, latency, size): [`scripts/compare_models.py`](https://github.com/cmu-seai/group-project-s26-model-impossible-1/blob/main/scripts/compare_models.py)

---

## Online Evaluation

### Model Accuracy Metric

**Metric:** We use two online metrics computed over a rolling 7-day attribution window:
- **Watch-through rate** — the fraction of recommended movie slots where the user actually watched the recommended movie within the 7 day period
- **Positive-rating rate** — the fraction of recommended slots where the user rated the recommended movie ≥ 4.0 within the 7 day period

Both measures were computed over the top-20 recommendations from each successful recommendation event.

**Telemetry collected:** Three event types are consumed in real time from the Kafka `movielog2` stream via `KafkaConsumer`, each parsed from the raw CSV format (`timestamp,userid,action`):
- `recommendation` events: `userid`, `timestamp`, `status` (HTTP status code), `recommendations` (comma-separated string of movie IDs)
- `watch` events: `userid`, `timestamp`, `movieid`, `minute`
- `rating` events: `userid`, `timestamp`, `movieid`, `rating` (1–5 scale)

Events are parsed by `parse_kafka_line()` in `scripts/online_eval.py`. Timestamps are extracted directly from the Kafka log line.

**Computation:** For each user, we chronologically align their recommendation events and downstream watch/rating events. For each successful recommendation event, we define a 7-day sliding window. A watch hit is counted when a watched `movieid` appears in the top-20 list and the watch timestamp falls within the window. A positive-rating hit is counted similarly, further requiring `rating ≥ 4.0`. The rate is: (total attributed hits) / (total recommended slots considered across all recommendation events). The script reports metrics at configurable intervals and writes final results to `models/artifacts/online_eval_results.json`.

### Cost Metric

**Metric:** Total system cost in USD, comprising (a) movie licensing fees — the per-view cost paid to the license holder each time a user watches a movie (from the `license_cost` field in the movie metadata JSON), and (b) LLM token costs for any external language model API calls. We report both the platform-wide total and the recommendation-attributed cost (only movies that were recommended by our model *and* subsequently watched).

**Telemetry collected:** Watch events from the Kafka stream (userid, movieid) and recommendation events (userid, movie list) are joined with the movie metadata (`metadata/movies.json`) which includes a `license_cost` field (USD per view). LLM token usage is tracked per API call (currently $0.00 as our pipeline does not use an external LLM).

**Operationalization:** For each watch event consumed from Kafka, we look up the movie's `license_cost` in the metadata and sum across all views to get the platform-wide licensing cost. To compute recommendation-attributed cost, we intersect each user's recommended movie list with their watched movies and sum only the license costs for those matched views. Per-recommendation-request cost = attributed_license_cost / total_recommendation_events. LLM costs are summed from any API call logs (currently $0). `Total cost = total_license_cost + llm_token_cost`.

### Evaluation Results

The online evaluation script connects directly to the Kafka `movielog2` stream via `KafkaConsumer`, collects events in real time, and reports metrics at configurable intervals. To run:

```bash
# 1. SSH tunnel to Kafka broker
ssh -L 9092:localhost:9092 <vm-host>

# 2. Run online evaluation (collects for 5 minutes, reports every 30s)
python scripts/online_eval.py --duration 300 --report-interval 30
```

Results are saved to [`models/artifacts/online_eval_results.json`](https://github.com/cmu-seai/group-project-s26-model-impossible-1/blob/main/models/artifacts/online_eval_results.json). Production snapshot (300-second live collection window, ~322K Kafka messages parsed, 3,283 recommendation events):

| Metric | Value |
|--------|-------|
| Watch-Through Rate | 0.586% (404 / 68,943 recommended slots) |
| Positive-Rating Rate | 0.0% (0 / 68,943 recommended slots) |
| Recommendations considered | 3,283 events |
| **Cost (recommendation-attributed)** | |
| Rec-attributed license cost | $109.22 (404 recommended-then-watched views) |
| Per rec-attributed view cost | $0.2703 |
| Per recommendation request cost | $0.0333 |
| **Cost (platform-wide)** | |
| Total platform license cost | $80,268.50 (380,236 total views) |
| Avg per-view license cost | $0.2111 |
| LLM token cost | $0.00 (no LLM used) |

The recommendation-attributed cost isolates only the license fees for movies that our model recommended *and* the user subsequently watched. The platform-wide total ($80K) reflects all views across ~51K users during the window, most of which are independent of our recommendations. The per-recommendation-request cost of $0.03 represents the actual licensing burden attributable to our model. The low positive-rating rate reflects the short 5-minute real-time window (`auto_offset_reset=latest`); users have not yet rated new recommendations within this timeframe.

### Implementation Pointer

- Online evaluation (WTR + cost, live Kafka): [`scripts/online_eval.py`](https://github.com/cmu-seai/group-project-s26-model-impossible-1/blob/main/scripts/online_eval.py)
- Tests for online metrics and Kafka parsing: [`tests/test_online_eval.py`](https://github.com/cmu-seai/group-project-s26-model-impossible-1/blob/main/tests/test_online_eval.py)

---

## Data Quality

### Schema Enforcement

We implemented schema validation for all four external data interfaces in [`src/data_quality.py`](https://github.com/cmu-seai/group-project-s26-model-impossible-1/blob/main/src/data_quality.py):

- **Kafka stream:** `validate_kafka_log_entry()` checks that each raw log line has the expected 3-field CSV structure (timestamp, userid, action), validates that the action matches one of the known event types (rating, watch, recommendation, signup), and enforces value ranges (e.g., ratings in [1, 5], watch minutes in [0, 600]). Malformed or unrecognized events are flagged with specific error messages.
- **User API:** `validate_user_api_response()` checks for required fields (`user_id`), correct types (e.g., `self_description_likes` must be a string), and rejects non-dict responses.
- **Movie API:** `validate_movie_api_response()` checks for required fields (`id`, `title`, `vote_average`, `genres`), validates that `vote_average` is in [0, 10], `genres` is a list, and `cost` (if present) is a non-negative number.
- **Recommendation API:** `validate_recommendation_request()` checks that the incoming user ID is non-empty and well-formed. `validate_recommendation_response()` validates that the output is a list of 1–20 unique, non-empty movie ID strings.

### Drift Detection

The `DriftDetector` class in the same module monitors for distribution shift in streaming data using a sliding window approach. It tracks three signals:

- **Rating mean shift:** Flags drift when the mean rating in the current window deviates from the reference mean by more than 0.5 points.
- **Event type distribution shift:** Flags drift when the max absolute difference in event type proportions exceeds 15%.
- **Watch duration shift:** Flags drift when the mean watch minutes shift by more than 30% relative to the reference.

Reference distributions are set from historical data, and the detector processes incoming events incrementally.

### Implementation Pointer

- Data quality module: [`src/data_quality.py`](https://github.com/cmu-seai/group-project-s26-model-impossible-1/blob/main/src/data_quality.py)
- Data quality tests (29 tests): [`tests/test_data_quality.py`](https://github.com/cmu-seai/group-project-s26-model-impossible-1/blob/main/tests/test_data_quality.py)

---

## Pipeline Implementation and Testing

### Pipeline Structure

The pipeline is organized into independent, reusable modules that can be run separately or end-to-end:

1. **Data ingestion:** `src/kafka_collector.py` consumes live events from the Kafka `movielog2` topic, parses each log line (rating, watch, recommendation, signup), and writes raw JSONL files. `scripts/run_kafka_ingest.py` downloads historical logs from GCS.
2. **Metadata collection:** `scripts/fetch_metadata.py` fetches user and movie metadata from the external APIs (`http://128.2.220.241:8080`) and saves them as `metadata/users.json` and `metadata/movies.json`.
3. **Data preparation:** `notebooks/data_prep.py` processes raw JSONL log files into clean CSVs (`data/processed/ratings.csv`, `watches.csv`, `recommendations.csv`, `signups.csv`).
4. **Model training:** `scripts/train.py` trains the NMF collaborative filtering model and the popularity-based model, saving artifacts to `models/artifacts/` (`.joblib` files + `training_metadata.json`).
5. **Offline evaluation:** `models/evaluate.py` loads models and test data, performs chronological train/test split, and computes NDCG@20. `scripts/compare_models.py` compares RMSE, latency, and size.
6. **Serving:** `src/app.py` (Flask) serves predictions at `GET /recommend/<userid>`. `src/recommender.py` implements the recommendation logic: cold-start → NMF → popularity → fallback.
7. **Data quality:** `src/data_quality.py` provides schema validation and drift detection for all data interfaces.
8. **Online evaluation:** `scripts/online_eval.py` computes WTR and cost metrics from the live Kafka stream.

Intermediate data is stored as CSV files in `data/processed/` and model artifacts as `.joblib` files in `models/artifacts/`. The pipeline can be re-run end-to-end after hyperparameter or data changes.

### Testing Approach

We use **pytest** with tests organized across four test modules:

| Test Module | Tests | What It Covers |
|-------------|-------|----------------|
| `tests/test_data_quality.py` | 29 | Schema validation for Kafka, User API, Movie API, Recommendation API; drift detection |
| `tests/test_pipeline.py` | 18 | Kafka log parsing, recommender logic (known/unknown users, cold start, popularity, edge cases), title matching |
| `tests/test_online_eval.py` | 24 | Kafka line parsing, WTR + positive-rating rate computation, cost metrics (attributed + platform-wide), edge cases |
| `tests/test_recommend.py` | 2 | Recommendation format (comma-separated, ≤20 IDs) and personalization |

Tests use **small synthetic data** rather than full production datasets. For the recommender tests, we rely on the actual model artifacts loaded lazily. For online evaluation and data quality tests, we construct minimal dicts and lists inline to test specific behaviors. Integration tests for Kafka, GCS, and external APIs are **skipped in CI** (marked with `pytest.skip` when `CI=true`) since they require network access to external services.

### Coverage Report

```
Name                       Stmts   Miss   Cover
------------------------------------------------
src/data_quality.py          169     14     92%
src/recommender.py            84     33     61%
scripts/online_eval.py       196    110     44%
------------------------------------------------
Overall (src + scripts)     1221    929     24%
```

Core modules under test have strong coverage. The lower overall figure reflects untested utility scripts (`fetch_metadata.py`, `run_kafka_ingest.py`, etc.) that are run manually and depend on external services.

### Adequacy Argument

Our testing focuses on critical and failure-prone components: (1) **data parsing** — the Kafka log parser is the entry point for all production data and is tested with valid, malformed, and edge-case inputs; (2) **data quality** — every external interface has schema validation tests covering both valid and invalid inputs; (3) **recommender logic** — all code paths (cold start, NMF, popularity, fallback) are exercised, and output format is verified; (4) **metric computation** — online accuracy and cost metrics are tested with known inputs/outputs. Components that are not unit-tested (e.g., GCS upload, Kafka connectivity) are integration-tested separately when running on the VM and are skipped in CI.

### Implementation Pointer

- Pipeline: [`src/`](https://github.com/cmu-seai/group-project-s26-model-impossible-1/tree/main/src), [`scripts/`](https://github.com/cmu-seai/group-project-s26-model-impossible-1/tree/main/scripts), [`notebooks/data_prep.py`](https://github.com/cmu-seai/group-project-s26-model-impossible-1/blob/main/notebooks/data_prep.py)
- Test suite: [`tests/`](https://github.com/cmu-seai/group-project-s26-model-impossible-1/tree/main/tests)
- CI coverage report: uploaded as artifact in each GitHub Actions run

---

## Continuous Integration

### CI Setup

We use **GitHub Actions** as our CI platform. The workflow is defined in [`.github/workflows/ci.yml`](https://github.com/cmu-seai/group-project-s26-model-impossible-1/blob/main/.github/workflows/ci.yml) and runs on `ubuntu-latest` with Python 3.10.

### What Is Automated

On every push or pull request to `main`, the CI pipeline automatically:

1. Checks out the repository.
2. Sets up Python 3.10 and installs all dependencies from `requirements.txt` plus `pytest` and `pytest-cov`.
3. Runs the full test suite (`pytest`) with coverage measurement for `src/` and `scripts/`.
4. Generates and uploads an HTML coverage report as a build artifact.

Integration tests that require external services (Kafka, GCS, external APIs) are automatically skipped in CI via the `CI=true` environment variable. Model training is **not** triggered by CI — it is run manually when needed.

### CI Service Pointer

- GitHub Actions dashboard: [https://github.com/cmu-seai/group-project-s26-model-impossible-1/actions](https://github.com/cmu-seai/group-project-s26-model-impossible-1/actions)
- Workflow file: [`.github/workflows/ci.yml`](https://github.com/cmu-seai/group-project-s26-model-impossible-1/blob/main/.github/workflows/ci.yml)

---

## Pull Requests *(optional)*

**Process description:** We use pull requests for feature branches targeting `main`. Each PR requires at least one team member review before merging. Reviewers check code quality, test coverage, and alignment with the milestone requirements.

**Example pull requests:**
1. [PR #1: Merge Sai Changes](https://github.com/cmu-seai/group-project-s26-model-impossible-1/pull/1) — integrated teammate's model training and data pipeline contributions into main.

---

## Team Contract Update

No update to team contract.
