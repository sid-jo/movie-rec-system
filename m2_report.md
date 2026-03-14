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

[TODO]

### Implementation Pointer

[TODO]

---

## Online Evaluation

### Model Accuracy Metric

**Metric:** We use two online metrics computed over a rolling 7-day attribution window:
- **Watch-through rate** — the fraction of recommended movie slots where the user actually watched the recommended movie within the 7 day period
- **Positive-rating rate** — the fraction of recommended slots where the user rated the recommended movie ≥ 4.0 within the 7 day period

Both measures were computed over the top-20 recommendations from each successful recommendation event.

**Telemetry collected:** Three event types are used from raw production logs (`data/raw_logs/*.jsonl`), each transformed into a JSON line with the following fields:
- `recommendation` events: `userid`, `timestamp`, `status` (HTTP status code), `recommendations` (list or comma-separated string of movie IDs)
- `watch` events: `userid`, `timestamp`, `movieid`
- `rating` events: `userid`, `timestamp`, `movieid`, `rating` (1–5 scale)

Events are parsed by `pipeline/telemetry.py` into typed `TelemetryEvent` dataclass instances. Timestamps are normalized to UTC-aware `datetime` objects and accept Unix epoch integers, ISO-8601 strings, or freeform date strings.

**Computation:** For each user, we chronologically align their recommendation events and downstream watch/rating events. For each successful recommendation event, we define a 7-day sliding window. A watch hit is counted when a watched `movieid` appears in the top-20 list and the watch timestamp falls within the window. A positive-rating hit is counted similarly, further requiring `rating ≥ 4.0`. The rate is: (total attributed hits) / (total recommended slots considered across all recommendation events). This is computed in `pipeline/online_eval.py` and written to `reports/online_eval.json`.

### Cost Metric

[TODO Ryan]

### Evaluation Results

[TODO]

### Implementation Pointer

- [`pipeline/online_eval.py`](group-project-s26-model-impossible-1/pipeline/online_eval.py) — accuracy proxy (watch-through rate, positive-rating rate)
- [`pipeline/online_cost.py`](group-project-s26-model-impossible-1/pipeline/online_cost.py) — licensing cost attribution
- [`pipeline/telemetry.py`](group-project-s26-model-impossible-1/pipeline/telemetry.py) — event parsing and normalization from raw log JSONL files

---

## Data Quality

*(0.5 pages max)*

### Schema Enforcement

<!-- Describe schema validation applied to:
- Kafka stream events
- User API responses
- Movie API responses
- Incoming requests to your recommendation API -->

### Drift Detection

<!-- Describe drift detection strategy:
- What signals are monitored
- How strong drift is detected
- How alerts or fallbacks are triggered -->

### Implementation Pointer

<!-- Link to implementation, e.g.:
[`data_quality/schema.py`](data_quality/schema.py)
[`data_quality/drift.py`](data_quality/drift.py) -->

---

## Pipeline Implementation and Testing

*(1 page of text max, not counting figures)*

### Pipeline Structure

<!-- Describe how the pipeline is structured and implemented:
- Modules/steps (data ingestion from Kafka, feature extraction, training, evaluation, model serialization, serving, telemetry)
- How steps can be run independently or end-to-end
- Any intermediate storage used (files, databases) -->

### Testing Approach

<!-- Describe how the pipeline was tested:
- Unit tests for each pipeline step
- Use of sample/mock data instead of full production datasets
- Mocks/stubs for network connections or external APIs
- Edge cases and robustness scenarios covered -->

### Coverage Report

<!-- Include or link to a coverage report, e.g.:
- Overall coverage: X%
- Link: [coverage report](link-to-coverage-report) -->

### Adequacy Argument

<!-- Briefly argue why the testing is adequate:
- Which components are most critical and how they are tested
- Known gaps and why they are acceptable -->

### Implementation Pointer

<!-- Link to pipeline and tests, e.g.:
[`pipeline/`](pipeline/)
[`tests/`](tests/) -->

---

## Continuous Integration

*(0.5 pages max)*

### CI Setup

<!-- Describe the CI platform used (e.g., GitHub Actions with local runner, Jenkins on VM) and the overall setup. -->

### What Is Automated

<!-- Describe what runs automatically on each push:
- Unit tests
- Coverage reporting
- Any other checks (linting, type checking, etc.)
Note: model training/evaluation pipeline automation is not required. -->

### CI Service Pointer

<!-- Provide a link to the CI service/dashboard.
If credentials are required, note that mentor access has been granted. -->

---

## Pull Requests *(optional)*

<!-- If your team used pull requests and code review for the majority of changes, provide:
- A brief description of your PR/review process
- Links to 3 example pull requests -->

**Process description:**

**Example pull requests:**
1. [PR title](link)
2. [PR title](link)
3. [PR title](link)

---

## Team Contract Update

<!-- Either:
(a) Include the updated team contract and describe the reason for the change, OR
(b) State: "No update to team contract." -->

No update to team contract.
