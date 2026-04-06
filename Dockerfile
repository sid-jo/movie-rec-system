# Inference service for GET /recommend/<userid> (gunicorn + Flask).
# Models and metadata are bind-mounted at runtime on the VM (see docker-compose.serving.yml).
FROM python:3.11-slim-bookworm

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    PIP_NO_CACHE_DIR=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

RUN useradd --create-home --uid 1000 app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src ./src
COPY metadata ./metadata
COPY experiments ./experiments
COPY models/artifacts ./models/artifacts

RUN mkdir -p experiments/logs \
    && chown -R app:app /app

USER app

EXPOSE 8082

# Graceful worker reload: docker kill -s HUP mlip-recommendation  (or scripts/run_rec_docker.sh reload)
CMD ["python", "-m", "gunicorn", "-w", "2", "-b", "0.0.0.0:8082", "src.app:app", \
     "--timeout", "120", "--graceful-timeout", "30"]

HEALTHCHECK --interval=30s --timeout=10s --start-period=45s --retries=3 \
    CMD curl -sf http://127.0.0.1:8082/health || exit 1
