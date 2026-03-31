#!/usr/bin/env bash
#
# Automated model retraining and deployment pipeline.
# Designed to be triggered by cron every 3 days.
#
# Steps:
#   1. Pull latest code from git
#   2. Ingest recent Kafka data
#   3. Fetch fresh metadata
#   4. Retrain models (NMF + popularity + cold-start)
#   5. Evaluate new model offline
#   6. Record model version + provenance
#   7. Hot-reload serving (gunicorn graceful restart)
#
# Usage: ./scripts/retrain_and_deploy.sh [--skip-ingest] [--skip-pull]
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
ARTIFACTS_DIR="$PROJECT_ROOT/models/artifacts"
LOG_DIR="$PROJECT_ROOT/logs"
mkdir -p "$LOG_DIR" "$ARTIFACTS_DIR"

TIMESTAMP=$(date +%Y%m%d_%H%M%S)
LOG_FILE="$LOG_DIR/retrain_${TIMESTAMP}.log"

exec > >(tee -a "$LOG_FILE") 2>&1

echo "=============================================="
echo "AUTOMATED RETRAINING PIPELINE"
echo "Started: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "=============================================="

# Cron jobs do not inherit your interactive SSH session — ensure Kafka tunnel exists
# before kafka_collector (requires localhost:9092). Copy .env.tunnel.example to .env.tunnel if needed.
if [ -x "$SCRIPT_DIR/ensure_kafka_tunnel.sh" ]; then
  if ! bash "$SCRIPT_DIR/ensure_kafka_tunnel.sh"; then
    echo "WARNING: Kafka tunnel not available (see logs/tunnel.log). Ingest step may fail or use stale data."
  fi
fi

SKIP_INGEST=false
SKIP_PULL=false
for arg in "$@"; do
    case $arg in
        --skip-ingest) SKIP_INGEST=true ;;
        --skip-pull)   SKIP_PULL=true ;;
    esac
done

cd "$PROJECT_ROOT"

# Step 1: Pull latest code
if [ "$SKIP_PULL" = false ]; then
    echo -e "\n--- Step 1: Pulling latest code ---"
    git pull --rebase origin main || echo "Git pull failed, continuing with current code"
fi

GIT_SHA=$(git rev-parse --short HEAD 2>/dev/null || echo "unknown")
echo "Git SHA: $GIT_SHA"

# Step 2: Ingest recent Kafka data (run collector for 5 minutes)
if [ "$SKIP_INGEST" = false ]; then
    echo -e "\n--- Step 2: Ingesting recent Kafka data (5 min) ---"
    timeout 300 python3 src/kafka_collector.py || echo "Kafka ingest completed or timed out"
fi

# Step 3: Fetch fresh metadata
echo -e "\n--- Step 3: Fetching metadata ---"
python3 scripts/fetch_metadata.py || echo "Metadata fetch failed, using existing"

# Step 4: Backup current models
echo -e "\n--- Step 4: Backing up current models ---"
BACKUP_DIR="$ARTIFACTS_DIR/backup_${TIMESTAMP}"
mkdir -p "$BACKUP_DIR"
for f in model_nmf.joblib model_popularity.joblib cold_start.joblib model_version.json; do
    [ -f "$ARTIFACTS_DIR/$f" ] && cp "$ARTIFACTS_DIR/$f" "$BACKUP_DIR/"
done
echo "Backed up to $BACKUP_DIR"

# Step 5: Retrain models
echo -e "\n--- Step 5: Training models ---"
python3 scripts/train.py

# Step 6: Record model version and provenance
echo -e "\n--- Step 6: Recording model version ---"
PREV_VERSION=1
if [ -f "$ARTIFACTS_DIR/model_version.json" ]; then
    PREV_VERSION=$(python3 -c "import json; print(json.load(open('$ARTIFACTS_DIR/model_version.json')).get('version', 0))" 2>/dev/null || echo "0")
fi
NEW_VERSION=$((PREV_VERSION + 1))

python3 -c "
import json, os, hashlib
from datetime import datetime

artifacts_dir = '$ARTIFACTS_DIR'

def file_hash(path):
    if not os.path.exists(path):
        return 'missing'
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(8192), b''):
            h.update(chunk)
    return h.hexdigest()[:12]

version_info = {
    'version': $NEW_VERSION,
    'trained_at': datetime.utcnow().isoformat() + 'Z',
    'git_sha': '$GIT_SHA',
    'pipeline_version': '$GIT_SHA',
    'training_data': {
        'ratings_csv': 'data/processed/ratings.csv',
        'watches_csv': 'data/processed/watches.csv',
        'movies_json': 'metadata/movies.json',
        'users_json': 'metadata/users.json',
    },
    'artifacts': {
        'model_nmf': file_hash(os.path.join(artifacts_dir, 'model_nmf.joblib')),
        'model_popularity': file_hash(os.path.join(artifacts_dir, 'model_popularity.joblib')),
        'cold_start': file_hash(os.path.join(artifacts_dir, 'cold_start.joblib')),
    },
    'backup_dir': '$BACKUP_DIR',
}
with open(os.path.join(artifacts_dir, 'model_version.json'), 'w') as f:
    json.dump(version_info, f, indent=2)
print(json.dumps(version_info, indent=2))
"

# Step 7: Offline evaluation (quick sanity check)
echo -e "\n--- Step 7: Offline evaluation ---"
python3 models/evaluate.py || echo "Evaluation failed, check logs"

# Step 8: Graceful restart of serving process
echo -e "\n--- Step 8: Reloading serving process ---"
if pgrep -f "gunicorn.*src.app" > /dev/null 2>&1; then
    echo "Sending HUP to gunicorn for graceful reload..."
    pkill -HUP -f "gunicorn.*src.app" || true
    echo "Gunicorn reloaded (zero-downtime model swap)."
else
    echo "No gunicorn process found. If running via flask directly, restart manually."
    echo "To start: gunicorn -w 2 -b 0.0.0.0:8082 src.app:app --timeout 120"
fi

echo -e "\n=============================================="
echo "RETRAINING COMPLETE"
echo "  Model version: $NEW_VERSION"
echo "  Git SHA: $GIT_SHA"
echo "  Log: $LOG_FILE"
echo "  Finished: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "=============================================="
