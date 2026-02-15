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
python src/scripts/fetch_metadata.py
# Output: metadata/users.json, metadata/movies.json (or similar)
```

Adjust paths and script names to match your project.

---

## 4. Train models (template)

Trains at least two models (e.g. collaborative filtering, content-based) and a cold-start handler. Saves artifacts under `models/saved/`.

```bash
# From repo root. Requires data/processed/ratings.csv, watches.csv, metadata/*.json
cd models
python train_models.py
```

**Expected outputs:**

| Output | Description |
|--------|-------------|
| `models/saved/cf_model.pkl` | Collaborative filtering model |
| `models/saved/cb_model.pkl` | Content-based model |
| `models/saved/cold_start.pkl` | Cold-start handler |
| `models/saved/training_metadata.json` | Training config and stats |

**Optional – evaluate models:**

```bash
cd models
python evaluate_models.py
```

---

## 5. Run tests (template)

Run project tests from repo root.

```bash
# From repo root
python -m pytest test/ -v

# Or run a specific test file
python -m pytest test/test_api_format.py -v
```

**Note:** Some tests may require network (course API) or GCS; skip or mock as needed for CI.

**Template – test categories:**

| Test file / dir | Purpose |
|-----------------|---------|
| `test/test_api_format.py` | User/movie API response format |
| `test/test_kafka.py` | Kafka parsing / connectivity |
| `test/test_gcs.py` | GCS sync (if used) |

Add or rename entries to match your `test/` layout.

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
- [ ] `models/train_models.py` runs and writes `models/saved/*.pkl`
- [ ] `pytest test/` runs (or known failing tests are documented)

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
│   ├── train_models.py
│   ├── evaluate_models.py
│   ├── collaborative_filtering.py
│   ├── content_based.py
│   ├── cold_start.py
│   └── saved/          # Trained models (after training)
├── data/
│   ├── raw_logs/       # Raw Kafka-style logs
│   └── processed/      # ratings.csv, watches.csv
├── metadata/           # users.json, movies.json
├── notebooks/          # data_prep.py, etc.
└── test/               # Unit/integration tests
```

Adjust this tree to match your repo; keep QUICKSTART in sync when you add or rename key paths.
