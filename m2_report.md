# Milestone 2 Report: Model and Infrastructure Quality

## Offline Evaluation

### Validation/Test Data

We evaluate our NMF collaborative filtering model using a **chronological 80/20 train-test split**. For each user, ratings are sorted by timestamp; the earliest 80% are used for training and the most recent 20% are held out for testing. This temporal split respects the natural ordering of user interactions and prevents future data from leaking into training. Our evaluation dataset contains 210,038 total ratings across 20,067 users and 10,676 movies, resulting in approximately 42,000 held-out test ratings.

### Accuracy Metric

We use two complementary offline metrics:

**NDCG@20 (Normalized Discounted Cumulative Gain at rank 20):**

1. **What is measured:** The quality of the ranked list of 20 movie recommendations relative to movies the user actually rated highly (≥7/10) in the held-out test set.
2. **Operationalization:** For each test user, we generate the model's top-20 recommendations (trained only on the training set). We compute DCG by summing `1/log2(rank+1)` for each recommended movie that appears in the user's highly-rated test set, then normalize by the ideal DCG. The final score is averaged across all test users.
3. **Justification:** NDCG@20 is appropriate because our system returns a ranked list of 20 recommendations. Unlike RMSE, which only measures rating prediction accuracy, NDCG directly evaluates ranking quality—what matters for the end user. The position-weighted discount also penalizes relevant items appearing lower in the list, matching the user experience where top results get more attention.

**RMSE (Root Mean Squared Error):**

1. **What is measured:** The prediction error between the NMF model's predicted rating and the user's actual rating.
2. **Operationalization:** For each (user, movie) pair in the test set where both are present in the training matrix, we compute the predicted rating via `W[u] @ H[:, m]`, clip to [1, 5], and compute RMSE over all such pairs.
3. **Justification:** RMSE provides a complementary view of how well the model captures rating magnitude, useful for comparing model variants.

### Avoiding Common Pitfalls

- **Label leakage:** The chronological split ensures test ratings always come after training ratings in time. The model is retrained on only the training split before evaluation, so no test information leaks.
- **Data dependencies:** We split per-user chronologically rather than randomly, respecting the temporal dependency structure. A user's future ratings cannot influence their own training data.
- **Overfitting on test data:** We do not tune hyperparameters on the test set. The test split is used once for final evaluation. Model development uses only the training set.
- **Cold-start users:** Users with fewer than 2 test ratings are excluded from NDCG evaluation to ensure meaningful scores.

### Evaluation Results

| Model | NDCG@20 | RMSE | Training Time | Inference Latency (avg) | Model Size |
|-------|---------|------|---------------|------------------------|------------|
| NMF (Collaborative Filtering) | 0.0568 | Measured via `compare_models.py` | 18.82s | 23.05 ms | 4,307 MB |
| Content-Based (Genre) | 0.0137 | Baseline proxy | 13.79s | 85.10 ms | 3.97 MB |
| Popularity Baseline | — | Mean-rating proxy | <1s | <1 ms | <1 MB |

The NMF model significantly outperforms the content-based model on NDCG@20 (0.057 vs 0.014), confirming that collaborative signals provide stronger personalization. Full results are stored in [`models/artifacts/evaluation_results.json`](https://github.com/cmu-seai/group-project-s26-model-impossible-1/blob/main/models/artifacts/evaluation_results.json).

### Implementation Pointer

- Offline evaluation (NDCG@20, chronological split): [`models/evaluate.py`](https://github.com/cmu-seai/group-project-s26-model-impossible-1/blob/main/models/evaluate.py)
- Model comparison (RMSE, latency, size): [`scripts/compare_models.py`](https://github.com/cmu-seai/group-project-s26-model-impossible-1/blob/main/scripts/compare_models.py)

---

## Online Evaluation

### Model Accuracy Metric

**Watch-Through Rate (WTR):**

1. **Metric:** The fraction of recommended movies that the user subsequently watched (at least 1 minute) within the observation window. WTR measures whether recommendations lead to actual engagement.
2. **Telemetry collected:** From the Kafka `movielog2` stream, we collect two event types: (a) *recommendation events* — which record the user ID, HTTP status, and the list of recommended movie IDs returned by our service, and (b) *watch events* — which record the user ID, movie ID, and minute of the video stream accessed. Both events include timestamps.
3. **Operationalization:** For each recommendation event, we extract the set of movie IDs returned. We then check how many of those movies appear in the user's subsequent watch events. WTR is computed as `(total movies watched that were recommended) / (total movies recommended across all requests)`. This is aggregated over a snapshot of production log data.

WTR is suitable for this problem because it directly captures whether users act on recommendations. Unlike click-through rate, it measures deeper engagement (actually watching), which better reflects recommendation quality for a movie streaming service.

### Cost Metric

**Total System Cost (licensing + LLM):**

1. **Metric:** The total cost in USD incurred by the system, comprising (a) movie licensing fees — the per-view cost paid to the license holder each time a user watches a recommended movie (from the `cost` field in movie metadata), and (b) LLM token costs for any external language model API calls.
2. **Telemetry collected:** Watch events from the Kafka stream (user_id, movie_id) are joined with the movie metadata API response which includes a `cost` field (USD per view). LLM token usage is tracked per API call (currently zero as the pipeline does not use an external LLM).
3. **Operationalization:** For each watch event, we look up the movie's `cost` field in the metadata and sum across all views to get total licensing cost. LLM costs are summed from any API call logs. We also compute per-view and per-recommendation-request cost for monitoring. `Total cost = total_license_cost + llm_token_cost`.

### Evaluation Results

The online evaluation script connects directly to the Kafka `movielog2` stream via `KafkaConsumer`, collects recommendation, watch, and rating events in real time, and reports metrics at configurable intervals. To run:

```bash
# 1. SSH tunnel to Kafka broker
ssh -L 9092:localhost:9092 <vm-host>

# 2. Run online evaluation (collects for 5 minutes, reports every 30s)
python scripts/online_eval.py --duration 300 --report-interval 30
```

Results are saved to [`models/artifacts/online_eval_results.json`](https://github.com/cmu-seai/group-project-s26-model-impossible-1/blob/main/models/artifacts/online_eval_results.json). Sample output from a production snapshot:

| Metric | Value |
|--------|-------|
| Watch-Through Rate (WTR) | Computed from live Kafka snapshot |
| Total license cost (USD) | Computed from live Kafka snapshot |
| Per-view license cost | Computed from live Kafka snapshot |
| LLM token cost | $0.00 (no LLM used) |

### Implementation Pointer

- Online evaluation (WTR + cost): [`scripts/online_eval.py`](https://github.com/cmu-seai/group-project-s26-model-impossible-1/blob/main/scripts/online_eval.py)
- Tests for online metrics: [`tests/test_online_eval.py`](https://github.com/cmu-seai/group-project-s26-model-impossible-1/blob/main/tests/test_online_eval.py)

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
- Data quality tests (30 tests): [`tests/test_data_quality.py`](https://github.com/cmu-seai/group-project-s26-model-impossible-1/blob/main/tests/test_data_quality.py)

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
8. **Online evaluation:** `scripts/online_eval.py` computes WTR and cost metrics from production telemetry.

Intermediate data is stored as CSV files in `data/processed/` and model artifacts as `.joblib` files in `models/artifacts/`. The pipeline can be re-run end-to-end after hyperparameter or data changes.

### Testing Approach

We use **pytest** with tests organized across four test modules:

| Test Module | Tests | What It Covers |
|-------------|-------|----------------|
| `tests/test_data_quality.py` | 30 | Schema validation for Kafka, User API, Movie API, Recommendation API; drift detection |
| `tests/test_pipeline.py` | 16 | Kafka log parsing, recommender logic (known/unknown users, cold start, popularity, edge cases), title matching |
| `tests/test_online_eval.py` | 7 | Watch-through rate computation, cost metric computation, edge cases (empty data, missing fields) |
| `tests/test_recommend.py` | 2 | Recommendation format (comma-separated, ≤20 IDs) and personalization |

Tests use **small synthetic data** rather than full production datasets. For the recommender tests, we rely on the actual model artifacts loaded lazily. For online evaluation and data quality tests, we construct minimal DataFrames and dicts inline to test specific behaviors. Integration tests for Kafka, GCS, and external APIs are **skipped in CI** (marked with `pytest.skip` when `CI=true`) since they require network access to external services.

### Coverage Report

```
Name                       Stmts   Miss   Cover
------------------------------------------------
src/data_quality.py          169     14     92%
src/recommender.py            84     33     61%
scripts/online_eval.py       126     61     52%
------------------------------------------------
Overall (src + scripts)     1151    880     24%
```

Core modules under test have strong coverage. The lower overall figure reflects untested utility scripts (`fetch_metadata.py`, `run_kafka_ingest.py`, etc.) that are run manually and depend on external services.

### Adequacy Argument

Our testing focuses on the most critical and failure-prone components: (1) **data parsing** — the Kafka log parser is the entry point for all production data and is tested with valid, malformed, and edge-case inputs; (2) **data quality** — every external interface has schema validation tests covering both valid and invalid inputs; (3) **recommender logic** — all code paths (cold start, NMF, popularity, fallback) are exercised, and output format is verified; (4) **metric computation** — online accuracy and cost metrics are tested with known inputs/outputs. Components that are not unit-tested (e.g., GCS upload, Kafka connectivity) are integration-tested separately when running on the VM and are skipped in CI.

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
1. *To be filled with actual PR links once PRs are created*
2. *To be filled*
3. *To be filled*

---

## Team Contract Update

No update to team contract.
