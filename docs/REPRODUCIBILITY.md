# Reproducibility Guide3

This document describes how to reproduce the movie recommendation pipeline using DVC (data/model versioning) and MLflow (experiment tracking).

## Prerequisites

1. **Python environment**
   ```bash
   # Use the project venv (avoids externally-managed-environment errors)
   ./venv/bin/pip install -r requirements.txt
   # Or: source venv/bin/activate && pip install -r requirements.txt
   ```

2. **GCS credentials** (for DVC remote)
   - Set `GOOGLE_APPLICATION_CREDENTIALS` to your service account key path
   - See [docs/GCS_SETUP.md](GCS_SETUP.md) for details

## First-time / After Clone

```bash
# Pull tracked data and models from DVC remote
dvc pull

# Install dependencies
./venv/bin/pip install -r requirements.txt
```

## Reproduce Full Pipeline

```bash
# Run all stages (prepare → train → evaluate) when deps change
dvc repro
```

## Run Stages Manually

```bash
# 1. Data preparation
python notebooks/data_prep.py

# 2. Model training
cd models && python train_models.py

# 3. Model evaluation
cd models && python evaluate_models.py
```

## Push/Pull Data and Models

```bash
# Upload tracked artifacts to GCS
dvc push

# Download tracked artifacts from GCS
dvc pull
```

## View Experiments (MLflow)

```bash
# Start MLflow UI
mlflow ui
```

Then open http://localhost:5000 to compare runs, params, metrics, and artifacts.

## Reproducibility Features

- **Random seeds**: `np.random.seed(42)` and `random.seed(42)` in train and evaluate scripts
- **Git commit**: Logged as MLflow param and in `training_metadata.json` for lineage
- **Pinned dependencies**: `requirements.txt` uses version pins for key packages
