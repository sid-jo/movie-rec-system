# Milestone 3 Report: Monitoring and Continuous Experimentation

## Containerization

*[To be completed by teammate]*

---

## Automated Model Updates

### Retraining Pipeline

We fully automate model retraining via [`scripts/retrain_and_deploy.sh`](https://github.com/cmu-seai/group-project-s26-model-impossible-1/blob/main/scripts/retrain_and_deploy.sh), a single script that performs the complete pipeline end-to-end:

1. **Data ingestion:** Runs `src/kafka_collector.py` for 5 minutes to collect the latest events from the Kafka `movielog2` stream.
2. **Metadata refresh:** Runs `scripts/fetch_metadata.py` to fetch updated user and movie metadata from the external APIs.
3. **Model backup:** Copies current model artifacts (`model_nmf.joblib`, `model_popularity.joblib`, `cold_start.joblib`) to a timestamped backup directory for rollback.
4. **Model training:** Runs `scripts/train.py` to retrain both the NMF collaborative filtering model and the popularity model on the latest data.
5. **Provenance recording:** Writes `models/artifacts/model_version.json` with a monotonically increasing version number, training timestamp, git SHA, SHA-256 hashes of all model artifacts, and pointers to the training data files used.
6. **Offline evaluation:** Runs `scripts/offline_eval.py` as a sanity check on the new joblib artifacts produced by `scripts/train.py` (not the legacy `models/evaluate.py` / `.pkl` path).
7. **Zero-downtime deployment:** Sends `SIGHUP` to the running gunicorn master (`src.app:app`), which gracefully reloads workers with the new model artifacts.

The script is triggered by cron every 3 days (see [`scripts/crontab.txt`](https://github.com/cmu-seai/group-project-s26-model-impossible-1/blob/main/scripts/crontab.txt)):
```
0 2 */3 * * cd $PROJECT_ROOT && bash scripts/retrain_and_deploy.sh --skip-pull >> logs/cron_retrain.log 2>&1
```

### Cold-Start Automation

New user signups are handled automatically by [`scripts/update_cold_start.py`](https://github.com/cmu-seai/group-project-s26-model-impossible-1/blob/main/scripts/update_cold_start.py). This script:

1. Monitors the Kafka stream for `create_account` events.
2. For each new user, fetches their `self_description_likes` and `self_description_dislikes` from the User API.
3. Matches mentioned movie titles against the catalog using the `title_to_id` mapping from `cold_start.joblib`.
4. Pre-computes personalized recommendations (liked movies first, then popular movies excluding disliked) and caches them in `models/artifacts/cold_start_cache.json`.

The script supports two modes:
- **Continuous (daemon):** Runs indefinitely, processing signups in real time.
- **One-shot (cron):** Runs for a configurable duration, suitable for periodic cron execution every 30 minutes.

### Implementation Pointers

- Retraining pipeline: [`scripts/retrain_and_deploy.sh`](https://github.com/cmu-seai/group-project-s26-model-impossible-1/blob/main/scripts/retrain_and_deploy.sh)
- Cold-start updater: [`scripts/update_cold_start.py`](https://github.com/cmu-seai/group-project-s26-model-impossible-1/blob/main/scripts/update_cold_start.py)
- Cron configuration: [`scripts/crontab.txt`](https://github.com/cmu-seai/group-project-s26-model-impossible-1/blob/main/scripts/crontab.txt)
- Service restart helper: [`scripts/restart_service.sh`](https://github.com/cmu-seai/group-project-s26-model-impossible-1/blob/main/scripts/restart_service.sh)

---

## Monitoring

### Infrastructure Setup

We use **Prometheus** for metrics collection and **Grafana** for visualization, deployed via Docker Compose ([`monitoring/docker-compose.yml`](https://github.com/cmu-seai/group-project-s26-model-impossible-1/blob/main/monitoring/docker-compose.yml)). The monitoring stack consists of three components:

1. **Flask app instrumentation** (`src/app.py`): The recommendation service exposes a `/metrics` endpoint using `prometheus_client`. Per-request metrics include:
   - `recommendation_requests_total` — counter by HTTP status and model type (cold_start, nmf, popularity, fallback)
   - `recommendation_latency_seconds` — histogram with configurable buckets
   - `recommendation_errors_total` — counter by error type
   - `recommendations_served_total` — total individual movie IDs served
   - `recommendation_service_up` — gauge (1 = healthy)

2. **Kafka metrics exporter** (`monitoring/metrics_exporter.py`): A standalone process on port 8083 that continuously consumes the Kafka `movielog2` stream and computes:
   - `online_watch_through_rate` — WTR gauge (real-time)
   - `online_positive_rating_rate` — PRR gauge (real-time)
   - `online_license_cost_usd_total` — cumulative platform-wide license cost
   - `online_rec_attributed_cost_usd_total` — cumulative recommendation-attributed cost
   - `online_rec_rate_per_minute` — recommendation events per minute (availability proxy from Kafka)
   - `kafka_stream_consumer_connected`, `kafka_consumer_last_successful_poll_timestamp_seconds`, `kafka_consumer_reconnects_total` — Kafka consumer / tunnel health (Grafana row **Kafka stream**)
   - `drift_rating_mean`, `drift_watch_duration_mean` — rolling distribution statistics
   - `drift_rating_shift_detected`, `drift_watch_duration_shift_detected` — binary drift alerts

   **Tunnel reliability:** `scripts/ensure_kafka_tunnel.sh` uses **autossh** when installed (`scripts/install_autossh.sh`) so an SSH tunnel drop to the course broker is automatically retried; consumers in the exporter and `scripts/update_cold_start.py` reconnect after broker errors.

3. **Prometheus + Grafana** (Docker): Prometheus scrapes both endpoints every 10-15 seconds. Grafana auto-provisions a pre-built dashboard via JSON provisioning.

### What We Monitor

| Category | Metrics | Source |
|----------|---------|--------|
| **(a) Availability** | Service up/down, uptime %, request rate, rec events/min from Kafka | Flask `/metrics` + Kafka exporter |
| **(b) Model accuracy** | Watch-Through Rate, Positive-Rating Rate, model distribution pie chart | Kafka exporter |
| **(c) Operating cost** | Total license cost, rec-attributed cost, cost rate ($/min). **LLM / API token cost** is $0 in this deployment (no external LLM on the inference path); the rubric’s license-fee side is covered by the Kafka-derived counters above (see also M2 cost write-up). | Kafka exporter |
| **(d) Data drift** | Rating mean shift (>0.5), watch duration shift (>30%), drift alert indicators | Kafka exporter |

### Alerts

We configured Prometheus alerting rules in [`monitoring/alerts.yml`](https://github.com/cmu-seai/group-project-s26-model-impossible-1/blob/main/monitoring/alerts.yml):

| Alert | Condition | Severity | Rationale |
|-------|-----------|----------|-----------|
| **ServiceDown** | Service unreachable for 2 min | Critical | Availability is graded; must detect downtime immediately |
| **MetricsExporterDown** | Scrape of `:8083` fails for 3 min | Warning | Loses Kafka-side accuracy, cost, drift, and Kafka health metrics |
| **KafkaConsumerDisconnected** | `kafka_stream_consumer_connected == 0` for 3 min | Critical | Tunnel/broker/consumer failure — stream processing stopped |
| **KafkaConsumerPollStalled** | Connected but no successful poll > 180s for 3 min | Warning | Detects hung client or partial tunnel failure |
| **HighErrorRate** | Error rate > 0.1/s for 3 min | Warning | Indicates model loading or API failure |
| **HighLatency** | p95 latency > 600ms for 5 min | Warning | Service must respond within time limit |
| **NoRecommendationTraffic** | 0 rec events in Kafka for 5 min | Critical | Service may be down even if HTTP is up |
| **RatingDriftDetected** | Rating mean shifted > 0.5 for 10 min | Warning | May indicate data quality injection |
| **WatchDurationDriftDetected** | Watch duration shifted > 30% for 10 min | Warning | May indicate behavioral change or data issue |

Alerts are justified because (1) availability is directly graded (70%+ required), (2) the course explicitly states they may inject data quality issues, and (3) cost spikes could indicate anomalous behavior. The 2-minute and 5-minute `for` durations prevent false positives from brief network blips.

### Dashboard Screenshot

Include Grafana exports showing **Service Availability** (request rate, latency, uptime), **Kafka stream** (consumer connected + poll lag), **Model Accuracy** (WTR/PRR), **Operating Cost**, and **Data Drift** — matching the provisioned dashboard [`monitoring/grafana/dashboards/recommendation-service.json`](monitoring/grafana/dashboards/recommendation-service.json). After deploying on the VM, capture from `http://<vm-ip>:3000/d/rec-service-dashboard` (refresh the dashboard JSON on the server if you added panels locally).

### Implementation Pointers

- Flask Prometheus instrumentation: [`src/app.py`](https://github.com/cmu-seai/group-project-s26-model-impossible-1/blob/main/src/app.py) (lines 23-57)
- Kafka metrics exporter: [`monitoring/metrics_exporter.py`](https://github.com/cmu-seai/group-project-s26-model-impossible-1/blob/main/monitoring/metrics_exporter.py)
- Prometheus config: [`monitoring/prometheus.yml`](https://github.com/cmu-seai/group-project-s26-model-impossible-1/blob/main/monitoring/prometheus.yml)
- Alert rules: [`monitoring/alerts.yml`](https://github.com/cmu-seai/group-project-s26-model-impossible-1/blob/main/monitoring/alerts.yml)
- Grafana dashboard: [`monitoring/grafana/dashboards/recommendation-service.json`](https://github.com/cmu-seai/group-project-s26-model-impossible-1/blob/main/monitoring/grafana/dashboards/recommendation-service.json)
- Docker Compose: [`monitoring/docker-compose.yml`](https://github.com/cmu-seai/group-project-s26-model-impossible-1/blob/main/monitoring/docker-compose.yml)
- Startup script: [`monitoring/start_monitoring.sh`](https://github.com/cmu-seai/group-project-s26-model-impossible-1/blob/main/monitoring/start_monitoring.sh)
- Grafana dashboard: http://\<vm-ip\>:3000/d/rec-service-dashboard (credentials: admin / mlip2026)

---

## Experimentation Infrastructure

*[To be completed by teammate]*

---

## Experiment Results

*[To be completed by teammate]*

---

## Provenance

*[To be completed by teammate]*

---

## Team Contract Update

No update to team contract.


