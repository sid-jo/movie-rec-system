# Milestone 2 Report: Model and Infrastructure Quality

## Offline Evaluation


### Validation/Test Data

Our data are in `data/processed/ratings.csv`, pulled from the production Kafka stream. Each row is a user–movie rating event on a 1–5 scale with a timestamp. The full dataset has roughly 210,000 ratings.

For the split, we go **per user, chronologically**: for each user we sort their ratings by timestamp and hold out the most recent 20% as the test set, with the remaining 80% for training (~42,000 test ratings). We do it this way rather than a global time cutoff because a global split would leave some users with no test data at all, and a random shuffle would leak future ratings into training.

### Accuracy Metric

**What we're measuring:** For each user, we check how well our recommender ranks the movies they actually liked (rated ≥ 4.0 out of 5) in their held-out period, specifically whether those movies show up near the top of the 20-item recommendation list.

**Operationalization (NDCG@20):** We use Normalized Discounted Cumulative Gain at k=20. For each user, the "relevant" set is the movies they rated ≥ 4.0 in their test split. DCG is:

$$\sum_{i=1}^{20} \frac{\mathbf{1}[\text{rec}_i \in \text{relevant}]}{\log_2(i+2)}$$

We divide by the ideal DCG (IDCG) to normalize to [0, 1], then average across all evaluated users. Users with no liked items in their test split are skipped and counted separately.

**Why this metric:** We serve exactly 20 recommendations per request, so k=20 directly matches what users actually see. NDCG rewards placing liked movies higher in the list rather than treating all positions equally, and normalizing means users with very different numbers of liked movies are still comparable.

### Avoiding Common Pitfalls

- **Label leakage:** Relevant items are defined only from test-split ratings — no test values are used at training time or to build features.
- **Temporal ordering:** The per-user chronological split means test ratings always come after training ratings for each user. A random split would let future likes leak into training.
- **Overfitting on the test set:** We fixed the metric and threshold (NDCG@20, rating ≥ 4.0) before looking at test results and only used the test split to report final numbers.

### Evaluation Results

| Model | NDCG@20 | Training Time | Inference Latency (avg) | Model Size |
|-------|---------|---------------|------------------------|------------|
| NMF (Collaborative Filtering) | 0.0568 | 18.82s | 23.05 ms | 4,307 MB |
| Content-Based (Genre) | 0.0137 | 13.79s | 85.10 ms | 3.97 MB |

The NMF model clearly outperforms content-based (0.057 vs 0.014). The absolute values are low, which is expected given how sparse the rating matrix is and the fact that cold-start users fall back to popularity-based recommendations entirely. Full results: [`models/artifacts/evaluation_results.json`](https://github.com/cmu-seai/group-project-s26-model-impossible-1/blob/main/models/artifacts/evaluation_results.json).

### Implementation Pointer

- Offline evaluation (NDCG@20, chronological split): [`scripts/offline_eval.py`](https://github.com/cmu-seai/group-project-s26-model-impossible-1/blob/main/scripts/offline_eval.py)
- Model comparison (RMSE, latency, size): [`scripts/compare_models.py`](https://github.com/cmu-seai/group-project-s26-model-impossible-1/blob/main/scripts/compare_models.py)

---

## Online Evaluation

### Model Accuracy Metric

**Metric:** We track two proxy metrics with a 7-day attribution window:
- **Watch-through rate** — out of all movies we recommended (top-20 per request), what fraction did the user actually watch within 7 days?
- **Positive-rating rate** — same, but the user also had to rate that movie ≥ 4.0

Both are computed over successful recommendation events only (HTTP 200).

**Telemetry collected:** We consume three event types from the live Kafka `movielog2` topic, parsed from the raw CSV format (`timestamp,userid,action`) by `parse_kafka_line()` in `scripts/online_eval.py`:
- `recommendation` events: userid, timestamp, HTTP status, comma-separated list of recommended movie IDs
- `watch` events: userid, timestamp, movieid
- `rating` events: userid, timestamp, movieid, rating (1–5)

**Computation:** For each user, we align their recommendation events with any downstream watch/rating events. For each successful recommendation, we open a 7-day window. A watch hit is when the user watches a recommended movie within the window. A positive-rating hit additionally requires `rating ≥ 4.0`. Final metric: (total hits) / (total recommended slots across all recommendation events). Results are written to `models/artifacts/online_eval_results.json`.

### Cost Metric

**Metric:** Total USD cost broken into two parts: (a) movie licensing fees — the per-view cost from the `cost` field in `metadata/movies.json` — and (b) LLM token costs (currently $0, we don't use an external LLM). We report both the platform-wide total and the recommendation-attributed portion (only movies we recommended that the user then actually watched).

**Telemetry collected:** Watch events and recommendation events from the same Kafka stream, joined with `metadata/movies.json` which has a `cost` field (USD per view) for each movie.

**Computation:** For each watch event, we look up the movie's `cost` and add it to the platform-wide total. For the attributed cost, we only count watches where the movie appeared in that user's most recent recommendation list within a 7-day window. Per-request cost = attributed cost / total recommendation events. LLM costs are tracked separately and are currently $0.

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

The $80K platform-wide total covers all views across ~51K users in the window, most of which have nothing to do with our recommendations. The $109 attributed cost is the portion we can actually tie to our model. The positive-rating rate being 0% makes sense for a short 5-minute window with `auto_offset_reset=latest` — users haven't had time to rate freshly recommended movies yet.

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

The pipeline is split into independent modules that can be run on their own or end-to-end:

1. **Data ingestion:** `src/kafka_collector.py` consumes live events from the Kafka `movielog2` topic, parses each log line (rating, watch, recommendation, signup), and writes raw JSONL files. `scripts/run_kafka_ingest.py` downloads historical logs from GCS.
2. **Metadata collection:** `scripts/fetch_metadata.py` fetches user and movie metadata from the external APIs (`http://128.2.220.241:8080`) and saves them as `metadata/users.json` and `metadata/movies.json`.
3. **Data preparation:** `notebooks/data_prep.py` processes raw JSONL log files into clean CSVs (`data/processed/ratings.csv`, `watches.csv`, `recommendations.csv`, `signups.csv`).
4. **Model training:** `scripts/train.py` trains the NMF collaborative filtering model and the popularity-based model, saving artifacts to `models/artifacts/` (`.joblib` files + `training_metadata.json`).
5. **Offline evaluation:** `scripts/offline_eval.py` loads the serving artifacts, performs the chronological split, and computes NDCG@20. `scripts/compare_models.py` compares RMSE, latency, and size.
6. **Serving:** `src/app.py` (Flask) serves predictions at `GET /recommend/<userid>`. `src/recommender.py` implements the recommendation logic: cold-start → NMF → popularity → fallback.
7. **Data quality:** `src/data_quality.py` provides schema validation and drift detection for all data interfaces.
8. **Online evaluation:** `scripts/online_eval.py` computes WTR and cost metrics from the live Kafka stream.

Intermediate data is stored as CSV files in `data/processed/` and model artifacts as `.joblib` files in `models/artifacts/`. The pipeline can be re-run end-to-end after hyperparameter or data changes.

### Testing Approach

We use pytest with tests split across four modules:

| Test Module | Tests | What It Covers |
|-------------|-------|----------------|
| `tests/test_data_quality.py` | 29 | Schema validation for Kafka, User API, Movie API, Recommendation API; drift detection |
| `tests/test_pipeline.py` | 18 | Kafka log parsing, recommender logic (known/unknown users, cold start, popularity, edge cases), title matching |
| `tests/test_online_eval.py` | 24 | Kafka line parsing, WTR + positive-rating rate computation, cost metrics (attributed + platform-wide), edge cases |
| `tests/test_recommend.py` | 2 | Recommendation format (comma-separated, ≤20 IDs) and personalization |

Tests use small synthetic data rather than full production datasets. For the recommender tests we load the actual model artifacts lazily; for online eval and data quality tests we just inline minimal dicts and lists to test specific behaviors. Integration tests (Kafka, GCS, external APIs) are skipped in CI via `pytest.skip` when `CI=true` since they need network access.

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

The core modules have solid coverage. The low overall figure is mostly due to utility scripts (`fetch_metadata.py`, `run_kafka_ingest.py`, etc.) that are run manually on the VM and depend on external services — not worth unit testing.

### Adequacy Argument

We focused testing on the parts most likely to break: (1) **Kafka parsing** — it's the entry point for all production data, so we test it with valid, malformed, and edge-case inputs; (2) **data quality** — every external interface has tests for both valid and invalid inputs; (3) **recommender logic** — all code paths (cold start, NMF, popularity, fallback) are covered and output format is verified; (4) **metric computation** — online accuracy and cost are tested against known inputs/outputs. GCS and Kafka connectivity aren't unit-tested but are covered by integration tests run on the VM.

### Implementation Pointer

- Pipeline: [`src/`](https://github.com/cmu-seai/group-project-s26-model-impossible-1/tree/main/src), [`scripts/`](https://github.com/cmu-seai/group-project-s26-model-impossible-1/tree/main/scripts), [`notebooks/data_prep.py`](https://github.com/cmu-seai/group-project-s26-model-impossible-1/blob/main/notebooks/data_prep.py)
- Test suite: [`tests/`](https://github.com/cmu-seai/group-project-s26-model-impossible-1/tree/main/tests)
- CI coverage report: uploaded as artifact in each GitHub Actions run

---

## Continuous Integration

### CI Setup

We use **GitHub Actions** as our CI platform. The workflow is defined in [`.github/workflows/ci.yml`](https://github.com/cmu-seai/group-project-s26-model-impossible-1/blob/main/.github/workflows/ci.yml) and runs on `ubuntu-latest` with Python 3.10.

### What Is Automated

Every push or pull request to `main` automatically:

1. Checks out the repo
2. Sets up Python 3.10 and installs `requirements.txt` + `pytest` + `pytest-cov`
3. Runs the full test suite with coverage over `src/` and `scripts/`
4. Uploads an HTML coverage report as a build artifact

Integration tests are skipped automatically via the `CI=true` env variable. We don't trigger model training from CI — that's run manually on the VM when needed.

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

### M2 work division (who / what / when)
- **Meeting notes (who / what / when):** [Meeting Notes](https://docs.google.com/document/d/1xYdYoa4klIVVYAxXRys2Vk8RwFHtYLldRd1g3595-I4/edit?usp=sharing) linked here
