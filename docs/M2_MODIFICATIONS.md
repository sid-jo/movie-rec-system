# Milestone 2 modifications (what changed to meet requirements)

This document summarizes the concrete code modifications added to meet the Milestone 2 requirements in `README.md` (pipeline entrypoints, testability, pytest suite + fixtures, data quality + drift, and online eval + online cost).

## Pipeline implementation (importable, independently callable steps)

- **Added `pipeline/` package** to standardize pipeline entrypoints as importable modules with `run(...)` functions and CLIs:
  - `pipeline/ingest.py`: download raw log blobs from GCS → `data/raw_logs/`
  - `pipeline/transform.py`: raw logs (`*.jsonl`) → `data/processed/{ratings,watches,recommendations,signups}.csv`
  - `pipeline/train.py`: trains serving-compatible artifacts → `models/artifacts/` (uses existing `scripts/train.py` logic)
  - `pipeline/offline_eval.py`: offline accuracy evaluation → `reports/offline_eval.json`
  - `pipeline/online_eval.py`: online accuracy proxy from telemetry → `reports/online_eval.json`
  - `pipeline/online_cost.py`: online licensing cost attribution → `reports/online_cost.json`
  - Shared paths/utilities: `pipeline/paths.py`, `pipeline/telemetry.py`

## Testability refactor (injectable external dependencies)

- **Course API calls (requests) made injectable**:
  - New `src/clients.py` defines `CourseApiClient` with injected `http` client.
  - `src/app.py` now uses `create_course_api_client()` instead of hardcoding `requests.get(...)`.

- **Kafka parsing centralized into a pure function**:
  - New `src/kafka_parsing.py:parse_log_entry(...)`
  - Updated collectors to reuse it:
    - `src/kafka_to_gcs.py`
    - `src/kafka_collector.py`

This enables offline unit tests and CI without Kafka/GCS/network.

## Pytest suite (fixtures + unit tests; integration tests opt-in)

- **Added pytest tooling**:
  - `requirements.txt`: added `pytest`, `pytest-cov`
  - `pytest.ini`: defines `integration` marker and default options

- **Added offline fixtures + unit tests**:
  - Fixtures:
    - `tests/fixtures/sample_raw_logs.jsonl`
  - Unit tests:
    - `tests/test_kafka_parsing_unit.py` (pure Kafka line parsing)
    - `tests/test_transform_unit.py` (raw→processed transform outputs)
    - `tests/test_clients_unit.py` (mocked course API client)
    - `tests/test_recommender_robustness_unit.py` (cold-start parsing + robustness)
    - `tests/test_recommend.py` (recommender output contract; skips if metadata missing)

- **Converted script-like tests into integration tests** (skipped unless enabled):
  - `tests/test_kafka.py` → `@pytest.mark.integration`
  - `tests/test_gcs.py` → `@pytest.mark.integration`
  - `tests/test_api_format.py` → `@pytest.mark.integration`

## Data quality: schema checks + drift detection

- **Schema validation utilities**:
  - `pipeline/data_quality.py`:
    - `validate_kafka_event(...)`
    - `validate_course_user(...)`
    - `validate_course_movie(...)`
    - `validate_recommend_response_text(...)`

- **Schema report generator**:
  - `pipeline/schema_check.py` → emits `reports/schema_report.json`

- **Drift report generator**:
  - `pipeline/drift.py` → emits `reports/drift_report.json`
  - Implements distribution comparisons (PSI/JS divergence) for:
    - rating distribution
    - recommendation status distribution
    - recommendation length distribution
    - licensing cost distribution (if `metadata/movies.json` contains `cost`)

## Online evaluation + online cost evaluation (JSON artifacts)

- **Telemetry parsing**:
  - `pipeline/telemetry.py` loads events from `data/raw_logs/*.jsonl` and normalizes timestamps/recommendation lists.

- **Online accuracy proxy**:
  - `pipeline/online_eval.py` computes:
    - watch-through rate within 7 days after a recommendation
    - positive-rating rate (rating ≥ 4.0) within 7 days after a recommendation
  - Outputs `reports/online_eval.json` and explicitly reports `llm_tokens: 0`.

- **Online cost**:
  - `pipeline/online_cost.py` attributes watch events to the most recent recommendation within 7 days and sums `metadata/movies.json` `cost`.
  - Outputs `reports/online_cost.json` and explicitly reports `llm_tokens: 0`.

