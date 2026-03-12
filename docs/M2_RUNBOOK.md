# Milestone 2 runbook (how to implement, run, and reproduce results)

This runbook shows how to run the pipeline entrypoints, tests, data quality checks, drift reports, and online eval/cost scripts added for Milestone 2.

## Setup

- **Install dependencies**:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

- **Required local files**:
  - `metadata/users.json`
  - `metadata/movies.json`
  - raw logs under `data/raw_logs/*.jsonl` (JSONL where each line is a dict with `type`, `userid`, `timestamp`, etc.)

If you don’t have these locally yet, use the ingest step (GCS → local) and your existing metadata fetch script.

## Pipeline entrypoints (single-command steps)

All entrypoints are importable modules and also runnable as:

```bash
python -m pipeline.<step> --help
```

### 1) Ingest (GCS → local raw logs)

Requires GCS credentials (see `docs/GCS_SETUP.md`).

```bash
python -m pipeline.ingest \
  --bucket mlip-team2-movielog \
  --prefix raw_logs/ \
  --output-dir data/raw_logs
```

### 2) Transform (raw logs → processed CSVs)

```bash
python -m pipeline.transform \
  --raw-logs-dir data/raw_logs \
  --output-dir data/processed
```

Outputs:
- `data/processed/ratings.csv`
- `data/processed/watches.csv`
- `data/processed/recommendations.csv`
- `data/processed/signups.csv`

### 3) Train (processed → serving artifacts)

This produces artifacts consumed by `src/recommender.py`.

```bash
python -m pipeline.train \
  --processed-dir data/processed \
  --metadata-dir metadata \
  --artifacts-dir models/artifacts
```

### 4) Offline evaluation (emit JSON artifact)

```bash
python -m pipeline.offline_eval \
  --processed-dir data/processed \
  --metadata-dir metadata \
  --artifacts-dir models/artifacts \
  --output reports/offline_eval.json
```

### 5) Schema checks (Kafka + metadata + recommend contract)

```bash
python -m pipeline.schema_check \
  --metadata-dir metadata \
  --output reports/schema_report.json
```

### 6) Drift report (schema + distribution drift)

- Without baseline (just compute current-window stats):

```bash
python -m pipeline.drift \
  --raw-logs-dir data/raw_logs \
  --metadata-dir metadata \
  --output reports/drift_report.json
```

- With baseline comparison:

```bash
python -m pipeline.drift \
  --raw-logs-dir data/raw_logs \
  --metadata-dir metadata \
  --baseline reports/drift_report_baseline.json \
  --output reports/drift_report.json
```

You can create a baseline by saving a previous `drift_report.json` (or the `"current"` subobject) as `reports/drift_report_baseline.json`.

### 7) Online evaluation (accuracy proxy from telemetry)

Computes watch-through and positive-rating rate within a 7-day window after recommendations.

```bash
python -m pipeline.online_eval \
  --raw-logs-dir data/raw_logs \
  --output reports/online_eval.json
```

### 8) Online cost evaluation (licensing cost from telemetry + metadata)

Attributes a watch to the user’s most recent recommendation within 7 days, then sums `movie.cost`.

```bash
python -m pipeline.online_cost \
  --raw-logs-dir data/raw_logs \
  --metadata-dir metadata \
  --output reports/online_cost.json
```

Both online artifacts explicitly include `llm_tokens: 0`.

## Tests + coverage

- **Unit tests (offline, default)**:

```bash
pytest
```

- **Integration tests (Kafka/GCS/course API)**:

```bash
RUN_INTEGRATION_TESTS=1 pytest -m integration
```

- **Coverage (example)**:

```bash
pytest --cov=src --cov=pipeline --cov-report=term-missing
```

## Using in `m2_report.md`

Recommended pointers (file links) for the report:
- Pipeline modules: `pipeline/`
- Tests: `tests/`
- Data quality + drift: `pipeline/schema_check.py`, `pipeline/drift.py`, `pipeline/data_quality.py`
- Online eval + cost: `pipeline/online_eval.py`, `pipeline/online_cost.py`
- Generated artifacts: `reports/*.json`

