# Security and Safety Report — Recommendation Service, Training Pipeline, and Monitoring

**Scope:** Team prediction service (`src/app.py`, `src/recommender.py`), automated retraining (`scripts/retrain_and_deploy.sh`, `src/kafka_collector.py`), Kafka-backed monitoring (`monitoring/metrics_exporter.py`), and Prometheus/Grafana stack (`monitoring/`).  
**Repository:** [group-project-s26-model-impossible-1](https://github.com/cmu-seai/group-project-s26-model-impossible-1) (paths below are relative to repo root).

---

## 1. Security risks (max ~2 pages)

### 1.1 Process used to identify security problems

We used a lightweight **threat-modeling pass** aligned with STRIDE-style thinking, focused on **data flows** and **trust boundaries**, rather than a full formal STRIDE workshop:

1. **Inventory assets:** User identifiers and profiles (via course User API), movie catalog, trained artifacts (`models/artifacts/*.joblib`), processed training tables (`data/processed/*.csv`), Kafka `movielog2` telemetry, GCS bucket contents for optional log sync, Grafana/Prometheus configuration and credentials.
2. **Map trust boundaries:** (a) Internet / grader clients → team VM `:8082`; (b) prediction service → User API `http://128.2.220.241:8080`; (c) VM → Kafka broker via SSH tunnel `localhost:9092`; (d) VM → GCS (optional); (e) team members → Docker daemon, shared VM accounts.
3. **Walk data flows** (evidence in code):
   - **Inference:** `GET /recommend/<userid>` loads optional user JSON from the User API then calls `get_recommendations` ([`src/app.py`](https://github.com/cmu-seai/group-project-s26-model-impossible-1/blob/main/src/app.py) — route `recommend`, `API_BASE`, `USER_TIMEOUT`).
   - **Training / refresh:** `kafka_collector.py` → `raw_data/`, optional GCS sync → `kafka_raw_to_jsonl_for_training.py` → `notebooks/data_prep.py` → `scripts/train.py` → artifacts consumed by gunicorn workers ([`scripts/retrain_and_deploy.sh`](https://github.com/cmu-seai/group-project-s26-model-impossible-1/blob/main/scripts/retrain_and_deploy.sh)).
   - **Telemetry:** `metrics_exporter.py` consumes Kafka and exposes Prometheus metrics; Prometheus scrapes Flask `/metrics` and exporter ([`monitoring/prometheus.yml`](https://github.com/cmu-seai/group-project-s26-model-impossible-1/blob/main/monitoring/prometheus.yml), [`monitoring/metrics_exporter.py`](https://github.com/cmu-seai/group-project-s26-model-impossible-1/blob/main/monitoring/metrics_exporter.py)).
4. **Per-component abuse cases:** For each boundary we asked: *Who can send input? What can they read or influence? What fails closed?* We recorded plausible attacks (below) where controls are weak or absent.

**Evidence this process was followed:** The analysis above is tied to concrete implementation pointers (Flask routes, retrain script, Prometheus scrape targets, alerts in [`monitoring/alerts.yml`](https://github.com/cmu-seai/group-project-s26-model-impossible-1/blob/main/monitoring/alerts.yml)). A short data-flow sketch used internally was:

`Client → :8082/recommend/{userid} → [User API] → recommender (NMF / popularity / cold-start) → response`  
`Kafka (read-only per course policy) → collector / exporter → disk or metrics`  
`Cron / operators → retrain script → processed CSV → new .joblib → HUP reload`

### 1.2 Plausible security issue A — **Attacks on / abusing the recommendation model (inference layer)**

**Description.** The recommendation endpoint is exposed as **`GET /recommend/<userid>`** without application-layer authentication or authorization in our service ([`src/app.py`](https://github.com/cmu-seai/group-project-s26-model-impossible-1/blob/main/src/app.py)). Any client that can reach the host (graders, scanners, or a leaked VM hostname) may issue a high volume of requests for **arbitrary** `userid` values.

**Why this is an attack on / against the model, not only “HTTP hygiene.”**

- **Model probing & user inference:** Responses encode up to 20 movie IDs derived from collaborative filtering, popularity, or cold-start logic over user-specific signals when the User API returns data ([`src/recommender.py`](https://github.com/cmu-seai/group-project-s26-model-impossible-1/blob/main/src/recommender.py) — `get_recommendations`, `get_model_type`, cold-start path using `self_description_likes`). An adversary can **harvest recommendation vectors** per user ID and correlate them with public catalog metadata to infer tastes, demographic proxies, or whether an account is “cold” vs established (path revealed via `model_type` labels in Prometheus: `recommendation_requests_total{model_type=...}`).
- **Workload abuse against model serving:** Unbounded requests force repeated **matrix factorization inference**, artifact I/O, and User API calls (short `USER_TIMEOUT` only limits stall, not volume — [`src/app.py`](https://github.com/cmu-seai/group-project-s26-model-impossible-1/blob/main/src/app.py)). This is a **resource exhaustion / DoS** vector against the **model serving path**, degrading availability for legitimate traffic (aligns with course availability grading but from a security lens it is abusive traffic).

**Plausibility:** Public assignment-style services commonly receive scanning traffic; our stack has no API key, no rate limit in application code, and no WAF described in-repo.

---

### 1.3 Plausible security issue B — **Integrity of the training / model artifact pipeline (supply chain on VM)**

**Description.** Retraining aggregates data from **local `raw_data/`**, optional **GCS JSONL**, and rebuilds **`data/processed/*.csv`** before writing new **`*.joblib`** files and reloading workers ([`scripts/retrain_and_deploy.sh`](https://github.com/cmu-seai/group-project-s26-model-impossible-1/blob/main/scripts/retrain_and_deploy.sh)). Model files are plain **`joblib`** loads in the serving process ([`src/recommender.py`](https://github.com/cmu-seai/group-project-s26-model-impossible-1/blob/main/src/recommender.py) — `joblib.load`).

**Risk.** Any principal with **shell access** to the shared team VM (or a compromised account) can:

- Replace or append **malicious content** to training inputs or directly swap **`model_nmf.joblib` / `model_popularity.joblib`** on disk.
- Trigger or wait for **cron** retrain / manual **`retrain_and_deploy.sh`** so the **next served model** reflects attacker-controlled weights (classic **backdoor / trojan model** scenario in ML ops).

Kafka is **read-only** for students per course policy, which **reduces** remote poisoning via the public broker but **does not** remove VM-local or insider tampering.

**Plausibility:** Shared course VMs with sudo-capable teammates are a standard insider / lateral-movement setting; `joblib.load` can execute arbitrary code if an attacker can place a crafted pickle (known Python security pitfall).

---

## 2. Mitigating security issues (max ~0.5 page)

### Issue A — Inference abuse & model probing

| Mitigation | Brief design change |
|------------|---------------------|
| **Authenticate callers** | Place the app behind **mutual TLS**, **VPN**, or an **API gateway** (OAuth2 client credentials or course-issued API keys) so only graders / frontend can call `/recommend`. |
| **Rate limiting** | Add per-IP and per-API-key **token bucket** limits (e.g. nginx `limit_req`, Envoy, or Flask middleware) and **cap distinct `userid` lookups per key per minute** to slow enumeration. |
| **Reduce leakage** | Avoid echoing internal **`model_type`** to untrusted clients in headers if not required; aggregate **`model_type`** only in internal metrics. |
| **Abuse detection** | Alert on **high cardinality of distinct userids per client IP** using access logs or a reverse proxy metric (extension to current Prometheus work). |

### Issue B — Training / artifact integrity

| Mitigation | Brief design change |
|------------|---------------------|
| **Signed artifacts** | Produce **SHA-256 manifests** of `*.joblib` and CSV inputs at train time; verify signature or hash **before** `joblib.load` in a small loader wrapper; refuse load on mismatch. |
| **Least privilege on VM** | Separate **train** user vs **serve** user; make artifact directory **read-only** for gunicorn; require **sudo** or CI-only for deploy writes. |
| **Safer serialization** | Prefer **formats with weaker arbitrary-code execution** than pickle where feasible, or load only from **trusted CI artifacts** built in isolated runners. |
| **Immutable deploy** | Deploy from **versioned container images** built in CI so the VM never runs `git pull` + arbitrary `joblib` from disk without verification ([`Dockerfile`](https://github.com/cmu-seai/group-project-s26-model-impossible-1/blob/main/Dockerfile) is a starting point). |

**If some mitigations are deferred:** For a closed course project, **documenting** default Grafana credentials ([`monitoring/docker-compose.yml`](https://github.com/cmu-seai/group-project-s26-model-impossible-1/blob/main/monitoring/docker-compose.yml)) and rotating them on the VM, plus **firewall rules** limiting `:8082` to grader IPs, may be proportionate **temporary** controls; full API auth may be deferred with that justification.

---

## 3. Analysis of a security issue using telemetry (max ~1 page)

### 3.1 Issue under test

**Issue A — abusive or probing traffic against `/recommend/<userid>`** (model probing and DoS-style load on inference). We asked: *Using only deployed telemetry, can we **observe** patterns consistent with an attack?*

### 3.2 How we analyzed (method)

1. **Confirm scrape path** — Prometheus scrapes the Flask `/metrics` endpoint on `127.0.0.1:8082` and the Kafka metrics exporter on `127.0.0.1:8083` ([`monitoring/prometheus.yml`](https://github.com/cmu-seai/group-project-s26-model-impossible-1/blob/main/monitoring/prometheus.yml)).
2. **Run reproducible PromQL** — We executed **instant** queries against the Prometheus HTTP API (`/api/v1/query`) for the same expressions our alerts use, plus request **rate by `model_type`**. The queries are implemented in the team notebook below (no manual copy-paste drift).
3. **Compare signals** — We compared **HTTP-side** `rate(recommendation_requests_total[...])` to **`online_rec_rate_per_minute`** from [`monitoring/metrics_exporter.py`](https://github.com/cmu-seai/group-project-s26-model-impossible-1/blob/main/monitoring/metrics_exporter.py) to reason about **organic Kafka traffic** vs **direct HTTP** to our VM.
4. **Cross-check alert rules** — We reviewed thresholds in [`monitoring/alerts.yml`](https://github.com/cmu-seai/group-project-s26-model-impossible-1/blob/main/monitoring/alerts.yml) (`HighErrorRate`, `HighLatency`, `NoRecommendationTraffic`) as the **operational definition** of “anomalous” for this stack.

### 3.3 Key findings (including negative results)

| Finding | Meaning |
|--------|--------|
| **Steady request rate, low errors, moderate p95 latency** | **Negative result for acute abuse** in the observation window: we did **not** see sustained alert-level error or latency excursions attributable solely from metrics (when Prometheus had data). |
| **No per-client identity in metrics** | **Negative result for attribution:** [`src/app.py`](https://github.com/cmu-seai/group-project-s26-model-impossible-1/blob/main/src/app.py) exports `recommendation_requests_total` with labels `status` and `model_type` only — **not** source IP or API key. A spike cannot be proven “attack” vs “grader burst” from Prometheus alone. |
| **Kafka vs HTTP divergence** | If HTTP rates are elevated while `online_rec_rate_per_minute` is low, traffic is **consistent with** synthetic access; that remains **circumstantial**, not a classifier for malice. |
| **Ethical constraint** | We did **not** run deliberate high-volume probing against the shared grader-facing host; conclusions rely on **organic** monitoring windows plus **notebook replay** on the VM when available. |

### 3.4 Artifacts (code and notebook — GitHub)

| Artifact | Role |
|----------|------|
| [`notebooks/security_telemetry_analysis.ipynb`](https://github.com/cmu-seai/group-project-s26-model-impossible-1/blob/main/notebooks/security_telemetry_analysis.ipynb) | **Primary analysis artifact:** runs PromQL via Prometheus HTTP API; set `PROMETHEUS_URL` if not on `127.0.0.1:9090`. |
| [`src/app.py`](https://github.com/cmu-seai/group-project-s26-model-impossible-1/blob/main/src/app.py) | Defines `recommendation_requests_total`, `recommendation_errors_total`, `recommendation_latency_seconds`. |
| [`monitoring/alerts.yml`](https://github.com/cmu-seai/group-project-s26-model-impossible-1/blob/main/monitoring/alerts.yml) | Alert expressions used as benchmarks for “unusual.” |
| [`monitoring/metrics_exporter.py`](https://github.com/cmu-seai/group-project-s26-model-impossible-1/blob/main/monitoring/metrics_exporter.py) | `online_rec_rate_per_minute` and drift gauges for cross-stream comparison. |

**Runbook (one line):** On the VM, start Prometheus per `monitoring/docker-compose.yml`, then `PROMETHEUS_URL=http://127.0.0.1:9090 jupyter nbconvert --execute notebooks/security_telemetry_analysis.ipynb --to notebook --inplace` (or open the notebook in Jupyter and run all cells).

---

## 4. Safety risks beyond fairness, feedback loops, and security (max ~2 pages)

**Deliberate scope boundary.** Our course write-ups already treat **statistical fairness**, **feedback-loop** effects of recommenders, and **cybersecurity** separately. This section addresses **product and operational safety** in the sense of **unintended harm to people or organizations** when the system behaves “as coded” but without safeguards that a production streaming product would require. We **did not** re-derive fairness metrics or threat models here.

### 4.1 Process used to identify possible safety problems (hazard analysis)

We used a compact **hazard analysis** workflow inspired by **FMEA-style** thinking (function → failure mode → scenario → harm), without claiming a regulated-device FMEA:

1. **List primary functions** of our slice: (a) rank and return up to 20 movie IDs; (b) blend **cold-start** text preferences with **global popularity**; (c) fall back to **fixed high-profile titles** when artifacts are missing ([`src/recommender.py`](https://github.com/cmu-seai/group-project-s26-model-impossible-1/blob/main/src/recommender.py)); (d) **automated retrain** from logs and redeploy ([`scripts/retrain_and_deploy.sh`](https://github.com/cmu-seai/group-project-s26-model-impossible-1/blob/main/scripts/retrain_and_deploy.sh)); (e) **monitoring** that may drive human actions ([`monitoring/alerts.yml`](https://github.com/cmu-seai/group-project-s26-model-impossible-1/blob/main/monitoring/alerts.yml)).
2. **For each function, ask “what if outputs are wrong or context is missing?”** — especially **viewer context** (age, mental state, co-viewing) that our API **does not accept** as inputs today.
3. **Trace to real-world harms** (not only “bad RMSE”): psychological distress, child safety, operational decisions under false alarms.
4. **Evidence we followed the process:** hazards below cite **actual code and metadata behavior** (no content-rating filter in recommender; `adult` exists in catalog JSON but is **not** consulted in ranking code).

### 4.2 Plausible safety issue A — **Psychological and trauma-related harm from ungated title lists**

**Hazard.** The recommender returns **titles only**; it does **not** apply **content warnings**, **intensity caps**, or **user vulnerability** signals. NMF and popularity paths maximize **statistical fit** to historical interactions, not **emotional safety**. The catalog includes **MPAA-style signals only indirectly** via TMDB fields such as `adult` in [`metadata/movies.json`](https://github.com/cmu-seai/group-project-s26-model-impossible-1/blob/main/metadata/movies.json), but **`get_recommendations` never filters on `adult` or genre** ([`src/recommender.py`](https://github.com/cmu-seai/group-project-s26-model-impossible-1/blob/main/src/recommender.py)).

**Plausible scenario.** A user in acute psychological distress receives **graphic violence or assault-themed** titles in the top-20 because similar users or popularity clusters correlate with “intense” thrillers. A **real-world harm** is **re-traumatization, sleep disruption, or acute anxiety** — the same class of harms that motivated **content sensitivity** features in large streaming products.

**Why this is not “fairness” or “security”.** It is not primarily a **disparate impact between groups** (fairness) nor an **adversary** (security); it is **normal operation without clinical or editorial guardrails**.

---

### 4.3 Plausible safety issue B — **Child and teen exposure when age context is absent**

**Hazard.** Cold-start fills from **user free-text** (`self_description_likes` / `dislikes`) then **tops up from global popularity** ([`src/recommender.py`](https://github.com/cmu-seai/group-project-s26-model-impossible-1/blob/main/src/recommender.py) lines 82–99). There is **no** `viewer_age`, **household profile**, or **parental control** channel in our service contract. Popularity and NMF paths likewise have **no age-aware gating** in code.

**Plausible scenario.** A **minor’s** account (or a shared family device misclassified as an adult) receives **R-rated or sexually explicit** recommendations because those titles rank highly in global popularity or latent factors. **Real-world harms** include **developmentally inappropriate exposure**, **parental conflict**, and **regulatory/reputational** exposure for a operator under COPPA-like or local child-safety expectations.

**Why this is not the “feedback loop” section.** The issue here is **missing age-appropriate policy in the decision layer**, not primarily **long-run popularity amplification** from a feedback loop (though loops could worsen exposure over time).

---

### 4.4 Summary

| Step | Evidence pointer |
|------|------------------|
| Hazard identification | Functions in [`src/recommender.py`](https://github.com/cmu-seai/group-project-s26-model-impossible-1/blob/main/src/recommender.py); catalog shape in [`metadata/movies.json`](https://github.com/cmu-seai/group-project-s26-model-impossible-1/blob/main/metadata/movies.json) (`adult` field unused in rec path). |
| Two distinct harms | **A:** trauma / distress from ungated intense content. **B:** child/teen exposure without parental controls in the API. |

**Design mitigations (brief):** integrate **content rating + blocker lists + optional “comfort mode”** in ranking; require **household/age signals** (or default to kid-safe) for any consumer deployment; show **warnings and “why recommended”** in UI layers beyond this assignment’s plain-text API.

---

*Document version includes telemetry notebook artifact and safety hazard analysis as required by the course prompt.*
