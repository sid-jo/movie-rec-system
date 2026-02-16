# Quickstart

Get the movie recommendation service running locally in a few steps. For full assignment details, see [README.md](README.md).

---

## Prerequisites

| Requirement | Notes |
|-------------|--------|
| **Python** | 3.10+ recommended |
| **Git** | To clone the repo |
| **(Optional) Kafka** | Only if you need to collect live stream data locally |
| **(Optional) GCP** | Only if using GCS sync (`src/sync_to_gcs.py`) |

---

## 1. Setup

```bash
# Clone (if not already)
git clone <repo-url>
cd group-project-s26-model-impossible-1

# Create and activate virtual environment
python3 -m venv venv
source venv/bin/activate          # Linux/macOS
# venv\Scripts\activate            # Windows

# Install dependencies
pip install -r requirements.txt
```

---

## 2. Run the recommendation API

The API serves recommendations at `GET /recommend/<userid>` and must return a single line of up to 20 comma-separated movie IDs.

```bash
cd src
python app.py
```

- Server runs at **http://0.0.0.0:8082** (or http://localhost:8082).
- Try: `curl http://localhost:8082/recommend/1`
- For production / grading, the course sends requests to your VM at port **8082** with a **600 ms** timeout.

**Template (customize for your stack):**

```text
# Option A: Development
python app.py

# Option B: Production (e.g. gunicorn)
gunicorn -w 4 -b 0.0.0.0:8082 app:app
```

---

## 3. Data preparation (template)

Training expects processed data under `data/processed/` and metadata under `metadata/`.

| File / directory | Description |
|-------------------|-------------|
| `data/raw_logs/*.jsonl` | Raw Kafka-style log files (if processing locally) |
| `data/processed/ratings.csv` | Columns: `user_id`, `movie_id`, `rating`, `timestamp` |
| `data/processed/watches.csv` | Columns: `user_id`, `movie_id`, `watch_count` (or equivalent) |
| `metadata/users.json` | User metadata from course API (or fetch script) |
| `metadata/movies.json` | Movie metadata from course API (or fetch script) |

**Template – from raw logs to processed CSVs:**

```bash
# From repo root. Ensure data/raw_logs/ and metadata/ exist.
python notebooks/data_prep.py
# Output: data/processed/ratings.csv, data/processed/watches.csv
```

**Template – fetch metadata only (if you have user/movie IDs):**

```bash
# Example: run from repo root; script may read from Kafka or a log file
python scripts/fetch_metadata.py
# Output: metadata/users.json, metadata/movies.json (or similar)
```

Adjust paths and script names to match your project.

---

## 4. Train models (template)

Trains at least two models (e.g. collaborative filtering, content-based) and a cold-start handler. Saves artifacts under `models/artifacts/`.

```bash
# From repo root. Requires data/processed/ratings.csv, watches.csv, metadata/*.json
cd models
python train.py
```

**Expected outputs:**

| Output | Description |
|--------|-------------|
| `models/artifacts/cf_model.pkl` | Collaborative filtering model |
| `models/artifacts/cb_model.pkl` | Content-based model |
| `models/artifacts/cold_start.pkl` | Cold-start handler |
| `models/artifacts/training_metadata.json` | Training config and stats |

**Optional – evaluate models:**

```bash
cd models
python evaluate.py
```

---

## 5. Run tests (template)

Run project tests from repo root.

```bash
# From repo root
python -m pytest tests/ -v

# Or run a specific test file
python -m pytest tests/test_api_format.py -v
```

**Note:** Some tests may require network (course API) or GCS; skip or mock as needed for CI.

**Template – test categories:**

| Test file / dir | Purpose |
|-----------------|---------|
| `tests/test_api_format.py` | User/movie API response format |
| `tests/test_kafka.py` | Kafka parsing / connectivity |
| `tests/test_gcs.py` | GCS sync (if used) |

Add or rename entries to match your `tests/` layout.

---

## 6. Environment and configuration (template)

Document any environment variables or config your team uses.

| Variable / config | Purpose | Example |
|------------------|---------|---------|
| `API_BASE` / user-movie API URL | Course user/movie API | `http://<ip>:8080` |
| Kafka bootstrap servers | Kafka consumer | From Canvas (M1) |
| GCP project / bucket | If using GCS | e.g. `mlip-spring2026` |

**Example `.env` (do not commit secrets):**

```bash
# .env.example – copy to .env and fill in
# USER_MOVIE_API=http://128.2.220.241:8080
# KAFKA_BOOTSTRAP_SERVERS=...
# GCP_PROJECT=...
```

Ensure `.env` is in `.gitignore` if it contains secrets.

---

## 7. End-to-end checklist (template)

Use this to verify a full run:

- [ ] `pip install -r requirements.txt` succeeds
- [ ] `src/app.py` runs and `curl http://localhost:8082/recommend/1` returns a comma-separated list (movie IDs)
- [ ] `data/processed/ratings.csv` and `watches.csv` exist (or data prep step is documented)
- [ ] `metadata/users.json` and `metadata/movies.json` exist (or fetch step is documented)
- [ ] `models/train.py` runs and writes `models/artifacts/*.pkl` (or `scripts/train.py` for NMF/Popularity)
- [ ] `pytest tests/` runs (or known failing tests are documented)

---

## Project layout (reference)

```text
.
├── README.md           # Full assignment
├── QUICKSTART.md       # This file
├── m1_report.md        # Milestone 1 report
├── requirements.txt
├── src/
│   ├── app.py          # Recommendation API (port 8082)
│   ├── kafka_collector.py
│   ├── kafka_to_gcs.py
│   └── scripts/        # Data fetch, etc.
├── models/
│   ├── train.py
│   ├── evaluate.py
│   ├── collaborative_filtering.py
│   ├── content_based.py
│   ├── cold_start.py
│   └── artifacts/      # Trained models (after training)
├── scripts/            # run_kafka_ingest.py, fetch_metadata.py, train.py, etc.
├── data/
│   ├── raw_logs/       # Raw Kafka-style logs
│   └── processed/      # ratings.csv, watches.csv
├── metadata/           # users.json, movies.json
├── notebooks/          # data_prep.py, etc.
└── tests/              # Unit/integration tests
```

Adjust this tree to match your repo; keep QUICKSTART in sync when you add or rename key paths.
