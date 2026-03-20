# Scripts (teammates) vs pipeline (your work) — where they overlap

This doc compares the **main-branch scripts/** and **src/** (teammates) with the **pipeline/** and related refactors (your work), so we can avoid duplicate logic and keep one clear place for each step.

---

## 1. Kafka stream and parsing

| Concern | Teammates (main) | Your work |
|--------|-------------------|-----------|
| **Raw Kafka line → struct** | `scripts/online_eval.parse_kafka_line()` (used only in that script) | `src/kafka_parsing.parse_log_entry()` (used by kafka_collector, kafka_to_gcs, pipeline/online_eval_live) |
| **Kafka validation (schema)** | `src/data_quality.validate_kafka_log_entry(raw_line)` — validates **raw** CSV line | *(removed: pipeline/data_quality was extra vs M2 report)* |
| **Tests** | `tests/test_online_eval.py` tests `parse_kafka_line`; `tests/test_data_quality.py` tests `validate_kafka_log_entry` | ~~`tests/test_kafka_parsing_unit.py`~~ (removed); `tests/test_pipeline.py` tests Kafka parsing with its in-file parser |

**Conclusion:** There are **three** Kafka parsers in the repo: `scripts/online_eval.parse_kafka_line`, `src/kafka_parsing.parse_log_entry`, and the one in `tests/test_pipeline.py`. Teammates’ live eval and tests are built around `parse_kafka_line`. Your `src/kafka_parsing` is the shared one used by collectors and pipeline. The test_pipeline copy is redundant with `src/kafka_parsing`.

---

## 2. Live online eval (Kafka stream → metrics)

| Aspect | Teammates | Your work |
|--------|-----------|-----------|
| **Entrypoint** | `scripts/online_eval.py` | `pipeline/online_eval_live.py` |
| **Behavior** | Connects to Kafka, consumes for `--duration`, computes WTR, positive-rating rate, license cost, per-view/per-rec, LLM=0, periodic reports, writes `models/artifacts/online_eval_results.json` | Same idea: Kafka for N seconds, same metrics, writes `reports/online_eval_live.json`, uses `src.kafka_parsing` + `pipeline.telemetry` |
| **Tests** | `tests/test_online_eval.py` (parse_kafka_line, compute_accuracy_metrics, compute_cost_metrics) | No dedicated tests for pipeline/online_eval_live |

**Conclusion:** **Live online eval is implemented twice.** Teammates’ version is the one with tests and is already the “canonical” script for real-time eval. **Recommendation:** treat **`scripts/online_eval.py`** as the single implementation for **live** online eval. Use it from the runbook (with the SSH tunnel). Optionally remove or thin **`pipeline/online_eval_live.py`** so it only forwards to or documents `scripts/online_eval.py`, to avoid maintaining two implementations.

---

## 3. File-based / snapshot online eval

| Aspect | Teammates | Your work |
|--------|-----------|-----------|
| **Source** | — | `data/raw_logs/*.jsonl` (ingested snapshot) |
| **Entrypoints** | — | `pipeline/online_eval.py`, `pipeline/online_cost.py` |

Teammates did **not** add a file-based online eval; they only have **live** Kafka eval in `scripts/online_eval.py`. Main-branch logic and m2_report treat online eval as **live stream only**. **Conclusion:** file-based online eval is **unnecessary**; use `scripts/online_eval.py` (with SSH tunnel) for all online eval. **Recommendation:** remove or stub **`pipeline/online_eval.py`** and **`pipeline/online_cost.py`** so there is a single place for online eval (scripts/online_eval.py).

---

## 4. Data quality

| Aspect | Teammates | Your work |
|--------|-----------|-----------|
| **Module** | `src/data_quality.py` | *(removed)* |
| **Kafka** | Validates **raw** log line (CSV string) | — |
| **User/Movie/Recommend API** | Same idea (schema checks) | — |
| **Usage** | `tests/test_data_quality.py` | *(removed to match M2 report)* |


### 4b. Removed to match M2 report

Pipeline `data_quality`, `drift`, and `schema_check` were removed. Data quality and drift are covered only by **src/data_quality.py** and **tests/test_data_quality.py** as in the report.

---

## 5. Ingest, transform, train, offline eval

| Step | Teammates (scripts) | Your work (pipeline) |
|------|----------------------|------------------------|
| **GCS → raw logs** | `scripts/run_kafka_ingest.py` (hardcoded paths, no CLI) | `pipeline/ingest.py` (CLI, injectable GCS client for tests) |
| **Raw → processed CSVs** | `notebooks/data_prep.py` (notebook-style) | `pipeline/transform.py` (importable `run()`, testable) |
| **Train serving models** | `scripts/train.py` (used by pipeline/train.py) | `pipeline/train.py` (wrapper that calls scripts/train logic) |
| **Offline eval** | — | `scripts/offline_eval.py` only. Output: `models/artifacts/offline_eval.json`. |

Teammates did **not** add a unified pipeline package. Your **pipeline/** gives a single set of entrypoints (`python -m pipeline.ingest`, etc.) and testable modules for ingest, transform, train. Data quality and drift are covered by the report’s **src/data_quality.py** and tests only.

---

## 6. Summary: what to keep vs simplify

- **Keep and use as canonical**
  - **Live online eval:** use **`scripts/online_eval.py`** (tested, matches teammate report format). Run with SSH tunnel as in the runbook.
  - **Kafka parsing in production:** keep **`src/kafka_parsing.parse_log_entry`** for collectors and any pipeline code that needs a shared parser; teammates’ `parse_kafka_line` stays for their script and tests.
- **Redundant / simplify**
  - **`pipeline/online_eval_live.py`** — duplicates live eval; recommend removing or making it a thin wrapper that calls `scripts/online_eval` so there is one implementation.
  - **`tests/test_pipeline.py`** — contains a duplicate parser; could be updated to use `src.kafka_parsing.parse_log_entry` instead of its own copy.
- **Keep (no overlap)**
  - **pipeline/** for: ingest, transform, train, paths, telemetry. Online eval redirects point to **scripts/online_eval.py**. Offline eval is **scripts/offline_eval.py** only (no pipeline module). Data quality/drift/schema_check removed to match M2 report.
  - **docs/M2_RUNBOOK.md**, **docs/M2_MODIFICATIONS.md** (if present).
  - **src/clients.py** (injectable API client).

---

## 7. Work you did that teammates have NOT included (keep these)

These exist only in your pipeline/ and refactors; main-branch scripts and src do not duplicate them:

| Area | What to keep |
|------|----------------|
| **Pipeline entrypoints** | `pipeline/ingest.py`, `pipeline/transform.py`, `pipeline/train.py` — unified, importable, testable steps. Offline eval is in `scripts/offline_eval.py` only. Teammates have `scripts/run_kafka_ingest.py`, `notebooks/data_prep.py`, `scripts/train.py` but no single package with `run()` + CLI. |
| **Shared infra** | `pipeline/paths.py`, `pipeline/telemetry.py` — used by transform, etc. (Data quality & drift: report uses **src/data_quality.py** only; pipeline layer removed.) |
| **Refactors** | `src/clients.py` (injectable course API client), `src/kafka_parsing.py` (shared parser for collectors and kafka_to_gcs). Teammates did not add injectable API or a shared parser module. |
| **Tests** | `tests/test_clients_unit.py`, `tests/test_transform_unit.py`, `tests/fixtures/sample_raw_logs.jsonl`. Teammates have test_online_eval, test_data_quality, test_pipeline but not these. Redundant tests removed: `test_kafka_parsing_unit.py` (duplicates test_pipeline Kafka parsing), `test_recommender_robustness_unit.py` (duplicates test_pipeline recommender + title-matching). |
| **Docs** | `docs/M2_MODIFICATIONS.md`, `docs/SCRIPTS_VS_PIPELINE.md` (and runbook if present). |

**Drop or stub (redundant / unnecessary with main):**

- **`pipeline/online_eval.py`** (file-based) — unnecessary; online eval = live Kafka only per main.
- **`pipeline/online_cost.py`** (file-based) — same; cost is in `scripts/online_eval.py`.
- **`pipeline/online_eval_live.py`** — duplicates `scripts/online_eval.py`; use script as canonical.

So: keep pipeline for **ingest, transform, train**, plus **paths**, **telemetry**, **src/clients**, **src/kafka_parsing**, and the extra tests. Use **`scripts/online_eval.py`** for online eval and **`scripts/offline_eval.py`** for offline eval. Data quality/drift/schema_check removed to align with M2 report.

---

## 8. Mapping your work to the M2 report (teammates’ m2_report.md)

The report describes what the team delivered. Below: what you did **supports** it (no conflict) vs what is **redundant** so you can avoid duplicating or conflicting with the report.

### Your work that supports the report (keep; no conflict)

| Report section | What report points to | Your work that supports it |
|----------------|------------------------|----------------------------|
| **Pipeline structure** | Ingestion (kafka_collector, run_kafka_ingest), data prep (notebooks/data_prep.py), train (scripts/train.py), data quality (src/data_quality), online eval (scripts/online_eval.py) | **pipeline/ingest.py** (CLI + injectable GCS), **pipeline/transform.py** (importable `run()`, replaces notebook-style prep), **pipeline/train.py** (wrapper around scripts/train). Unified entrypoints. |
| **Testing** | test_data_quality, test_pipeline, test_online_eval, test_recommend; “test all data transformation code”; mocks for network | **tests/test_transform_unit.py** (transform step), **tests/test_clients_unit.py** (injectable API client). Extra coverage without conflicting. |
| **Data quality** | src/data_quality.py (schema + DriftDetector), tests/test_data_quality.py | Pipeline data_quality/drift/schema_check **removed** so pipeline matches report (report only points to src/data_quality). |
| **Offline eval** | models/evaluate.py (NDCG@20, chronological split), scripts/compare_models.py | **scripts/offline_eval.py** — same metric (NDCG@20) and per-user chronological split, but evaluates the **served** recommender (`get_recommendations`). Report points to models/evaluate.py; your script is an additional entrypoint. No conflict. |
| **Infrastructure / testability** | CI runs pytest; integration tests skipped when CI=true | **src/kafka_parsing.py** (shared parser for collectors), **src/clients.py** (injectable API). Supports testability and pipeline steps. |
| **Paths / telemetry** | (not in report) | **pipeline/paths.py**, **pipeline/telemetry.py** — used by transform, etc. Supports pipeline only. |

### Redundant or conflicting work (simplify so report stays single source of truth)

| Report says | Your redundant piece | Action to avoid conflict |
|-------------|----------------------|---------------------------|
| **Online evaluation:** “scripts/online_eval.py”, “parse_kafka_line()”, “models/artifacts/online_eval_results.json”, runbook: `python scripts/online_eval.py --duration 300 --report-interval 30` | **pipeline/online_eval_live.py** — same behavior (live Kafka, WTR + cost), different output path. Report does not mention it. | Treat **scripts/online_eval.py** as canonical. Make pipeline/online_eval_live a **thin wrapper** that calls the script (or remove it) so the report’s pointer and runbook stay accurate. |
| Online eval = live Kafka only; no file-based online eval in report | **pipeline/online_eval.py**, **pipeline/online_cost.py** (file-based) | Stub or remove; report and runbook only describe live Kafka. |

### Summary

- **Keep and use:** pipeline ingest, transform, train; paths, telemetry; src/clients, src/kafka_parsing; scripts/offline_eval.py; test_transform_unit, test_clients_unit. Data quality/drift/schema_check removed to match M2 report.
- **Align with report (no duplicate implementations):** Use **scripts/online_eval.py** for online eval; thin or remove pipeline/online_eval_live and drop file-based pipeline/online_eval and pipeline/online_cost so the report’s pointers and runbook stay the single source of truth.
