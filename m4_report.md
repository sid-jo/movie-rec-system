# Milestone 4 Report: Fairness, Security, and Feedback Loops

**Repository:** [cmu-seai/group-project-s26-model-impossible-1](https://github.com/cmu-seai/group-project-s26-model-impossible-1)

This report matches the implementation on `main`. All code, notebooks, and artifacts referenced below are linked relative to the repo root. Numbers in `[brackets]` are filled by the analysis scripts and updated on each run.

---

## Fairness Risks

### (a) Understanding potential fairness harms

We classified harms against the Barocas/Hardt/Narayanan taxonomy and mapped each to a concrete part of our deployed pipeline.


| Harm type                        | Where it manifests in our system                                                                                                                                                                                                                                                                                                  |
| -------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Quality-of-service (users)       | `_extract_movies_from_description` ([src/recommender.py:58](src/recommender.py#L58)) regex-matches catalog titles inside free-text `self_description`. Users whose descriptions are short, non-English, or abstract never hit this branch and are routed to the popularity fallback — they get materially less personalised recs. |
| Allocational (content providers) | The popularity fallback ([src/recommender.py:156-163](src/recommender.py#L156-L163)) returns a hash-shifted slice of `_top_movies`, so nearly every low-signal request shows the same ~20 mainstream titles. International / indie providers are squeezed out of the slot budget.                                                 |
| Stereotyping                     | NMF is trained on historical watch / rating matrices whose latent factors encode gender- and age-correlated preference patterns.                                                                                                                                                                                                  |
| Feedback amplification           | A user who gets poor recs watches / rates less, reducing their signal at the next retrain (cron every 3 days — [scripts/retrain_and_deploy.sh](scripts/retrain_and_deploy.sh)), so the disparity compounds.                                                                                                                       |


### (b) Exploring bias in data and its sources

We audited the three data sources that feed production (scripts under [scripts/fairness_analysis.py::describe_bias](scripts/fairness_analysis.py)):

- **Catalog (**`metadata/movies.json`**, 10,676 titles)** is heavily English-language dominated and skews toward pre-2010 mainstream titles with`budget > 0`. Non-English and low-budget titles are severely under-represented relative to the real-world global catalog.
- **User metadata (`metadata/users.json`, 46,258 users)** provides `age`,`gender`, `occupation`, and the free-text `self_description_likes` /`_dislikes`. The self-description text is an *English-centric filter* because the downstream title-extraction regex works on catalog titles whose keys are English-normalised strings.
- **Training traces (NMF)** are built from historical Kafka watches. Users who were under-served in earlier windows already have sparse rows, so latent factors are noisier for them — *bias-in becomes bias-out*.

### (c) Identifying protected attributes


| Side     | Attributes                                                                                                        |
| -------- | ----------------------------------------------------------------------------------------------------------------- |
| User     | `gender` (M/F), `age` (bucketed `<18, 18-25, 26-40, 41-60, 60+`), `occupation` — all available from the User API. |
| Provider | `original_language`, `origin_country`, `budget_quartile`, `release_decade` — from the Movie API.                  |


### (d) Negotiating conflicting fairness goals

Two concrete tensions we resolved explicitly:

- **Equal WTR across user groups vs. equal exposure across languages.**  
Enforcing non-English quotas for users who prefer English reduces their WTR. We chose *equal quality-of-service across user demographics* as the primary user-side goal, and *floor-style* exposure parity on the provider side (a minimum share per language, not equal shares). This protects small catalogs without forcing equal shares to dominant-language content.
- **Group parity vs. individual accuracy.** Strict per-group parity on a per-user metric can force individually-worse recs on majority-group users. We picked a threshold-based gap (not equality) so the system only intervenes once gaps are materially harmful.

### (e) Fairness interacting with other system goals


| Other goal               | Interaction                                                                                                                                                                                                                                  |
| ------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **License cost**         | `exp_cost_optimise` ([experiments/exp_cost_optimise.json](experiments/exp_cost_optimise.json)) re-ranks to cheaper titles. We currently do not monitor whether this assignment widens or narrows language exposure — a latent fairness risk. |
| **Latency (600 ms SLA)** | Any post-hoc fairness re-ranker must stay inside the Flask request path. A language-quota re-ranker adds O(20) metadata lookups, well within budget.                                                                                         |
| **User engagement**      | Low WTR for a group → fewer watch events from that group → sparser training rows → even lower quality at the next retrain. Drives the feedback-loop risks in a later section.                                                                |


### Fairness requirements

**R1 — Recommendation service, group quality-of-service.**  
*Within a 7-day window containing ≥10k rated/watched events per compared group, the mean rating and mean watch-volume per user must not differ by more than **10%** between male and female users, and the max-min ratio across age buckets must be ≥ **0.8**.*  
Justification: this operationalises the quality-of-service harm in (a) using engagement telemetry we currently have. Thresholds are loose enough to avoid chasing noise but tight enough that sustained violations are meaningful.  
Measure: (i) per-group mean rating and per-user-mean-watch-count with Wilson 95% CIs and a two-sample Welch *t*-test on male vs. female users; (ii) across the five age buckets, compute the ratio `min(metric) / max(metric)` for both mean rating and mean watch-count — the requirement passes iff this ratio is ≥ 0.8 for both metrics.
Implementation: [src/analysis/fairness.py::group_engagement](src/analysis/fairness.py) returns per-group aggregates for gender *and* age buckets, and the age ratio is computed from the returned dict.

**R2 — System-wide, provider exposure floor.**
*For every* `original_language` *with ≥20 titles in the catalog, the ratio*`play_share / catalog_share` *must be ≥ **0.5** averaged over a 7-day window, where* `play_share` *is the fraction of all recorded watches attributed to that language.*  
Justification: operationalises the allocational harm in (a). A floor avoids penalising dominant-language content while preventing small catalogs from being reduced to zero exposure in practice.  
Measure: `min_lang (play_share / catalog_share)` for eligible languages;
[src/analysis/fairness.py::exposure_parity_by_plays](src/analysis/fairness.py).

---

## Fairness Improvement Suggestions

**R1 — quality-of-service parity.**

- *Beyond-model (monitoring + operation).* Add three Grafana panels backed by the existing Prometheus scraper ([monitoring/metrics_exporter.py](monitoring/metrics_exporter.py)): per-user-mean watch count by gender, by age bucket, and the live gender gap. Alert through [monitoring/alerts.yml](monitoring/alerts.yml) when the gender gap exceeds 10 % for ≥ 7 days with ≥ 10k users per group. The alert triggers a human-review workflow (not an auto-rollback) because small-N drift is common.
- *Model-side.* In `pipeline/train.py`, stratify the validation split by`gender × age` cell and compute per-cell loss; use a group-balanced sampler so under-represented cells get proportional gradient weight.

**R2 — provider exposure floor.**

- *System design.* Add a post-hoc re-ranker in [src/recommender_variants.py](src/recommender_variants.py) analogous to `_apply_cost_rerank`: given a 20-movie candidate list, guarantee at least one slot for the currently-underexposed language(s) when any candidate qualifies. Ship it behind a new experiment `exp_language_quota` so we measure the WTR cost of the parity gain empirically.
- *Process integration.* Extend [scripts/retrain_and_deploy.sh](scripts/retrain_and_deploy.sh) with a gate that runs `fairness_analysis.py` on the last 7 days before SIGHUP’ing gunicorn; if R2’s ratio drops below 0.5 the gate blocks the deploy and logs to `logs/fairness_gate.log` for team review.

---

## Fairness Analysis

We analysed **R2 (provider exposure by plays)**.

**Data.** Telemetry captured from the production Kafka `movielog2` stream via [src/kafka_collector.py](src/kafka_collector.py) and dumped to [data/raw_logs/*.jsonl](data/raw_logs/) — 3,500 JSONL shards, containing **34,773,935 watch events** and **216,548 rating events** produced by real user activity against our deployed recommender. We verified the watch-event regex by sampling events.

**Method.** Code: [src/analysis/fairness.py](src/analysis/fairness.py) + [scripts/fairness_analysis.py](scripts/fairness_analysis.py). Results JSON: [experiments/results/m4_fairness.json](experiments/results/m4_fairness.json).

1. Stream all JSONL shards; count `type == "watch"` events per `movie_id` (34.77 M plays across 10,676 catalog titles).
2. Join each movie to `metadata/movies.json` to get `original_language`.
3. Compute `play_share[lang] = plays[lang] / total_plays` and `catalog_share[lang] = titles[lang] / total_titles`.
4. For each language with ≥ 20 catalog titles, report `ratio = play_share / catalog_share`. R2 passes if `min_lang(ratio) ≥ 0.5`.

### Findings

Language exposure — catalog share vs. play share, top 10 languages by catalog share


| Language | Catalog titles | Catalog share | Play share | Ratio     | Meets 0.5 floor? |
| -------- | -------------- | ------------- | ---------- | --------- | ---------------- |
| en       | 9,082          | 0.8507        | 0.9533     | **1.121** | ✓                |
| fr       | 447            | 0.0419        | 0.0132     | 0.315     | ✗                |
| ja       | 221            | 0.0207        | 0.0076     | 0.365     | ✗                |
| it       | 136            | 0.0127        | 0.0053     | 0.413     | ✗                |
| es       | 122            | 0.0114        | 0.0036     | 0.315     | ✗                |
| de       | 115            | 0.0108        | 0.0050     | 0.465     | ✗                |
| hi       | 57             | 0.0053        | 0.0004     | 0.082     | ✗                |
| ru       | 40             | 0.0037        | 0.0006     | 0.155     | ✗                |
| ko       | 38             | 0.0036        | 0.0007     | 0.187     | ✗                |
| no       | 20             | 0.0019        | 0.0001     | **0.072** | ✗                |
| fi       | 20             | 0.0019        | 0.0001     | **0.053** | ✗                |


Minimum ratio across eligible languages: **0.053** (Finnish).
R2 threshold (0.5) met: **No**. **14 of 15** non-English languages with ≥ 20 catalog titles fall below the 0.5 floor; several (fi, no, hi) fall below 0.1 — their films are recommended and watched at less than one-tenth the rate a neutral system would produce.

### Interpretation

English titles are 85 % of the catalog but capture 95 % of plays (ratio 1.12×), while Finnish, Norwegian and Hindi films see less than 10 % of their neutrally-expected share. Because plays in our system are almost entirely driven by what we recommend (the simulator's users click recs rather than searching), this distribution is a direct downstream signature of the recommender's output.

The mechanism is structural and traceable in our code:

- The **popularity fallback** ([src/recommender.py:156-163](src/recommender.py#L156-L163)) returns a hash-shifted slice of `_top_movies` — itself learned from historically English-heavy watch counts — for every low-signal user.
- The **cold-start extraction** ([src/recommender.py:58-70](src/recommender.py#L58-L70)) can only match titles users wrote in English against English-normalised catalog keys.
- The **hardcoded fallback list** at [src/recommender.py:169-180](src/recommender.py#L169-L180) is 10 English titles.
- The **3-day retrain cron** ([scripts/retrain_and_deploy.sh](scripts/retrain_and_deploy.sh)) feeds today's English-skewed watches back into tomorrow's `_top_movies`, amplifying the bias with every cycle.

---

## Anticipating Feedback Loops

*TODO — fill during the feedback-loop track.*

## Mitigating a Negative Feedback Loop

*TODO*

## Analysis of a Feedback Loop

*TODO* 

---

## Security Risks

### Systematic threat modeling (STRIDE-aligned)

We analyzed the deployed recommendation stack using a **STRIDE-style** elicitation (Spoofing, Tampering, Repudiation, Information disclosure, Denial of service, Elevation of privilege), mapped onto **concrete data flows** in our repository. The goal was not to produce a formal Microsoft SDL workbook, but to ensure each STRIDE category was exercised against **actual entry points** (HTTP routes, batch ingest, model load, observability) so that residual risks are traceable to code.

**Data-flow trace (user input → output).** Externally originated traffic arrives at the Flask application on the team VM ([src/app.py](src/app.py), module-level `app = Flask(__name__)`). The primary user-controlled surface is the **path parameter** `userid` in `GET /recommend/<userid>`, which is constrained by `_USERID_RE` and `validate_recommendation_request` ([src/app.py](src/app.py) lines 36–41, 115–127) before any downstream call. For valid identifiers, the service optionally hydrates **user profile JSON** via `CourseApiClient` against `USER_API_BASE` (default `http://128.2.220.241:8080`, [src/app.py](src/app.py) lines 33–34, 129–134). That profile—including `self_description_likes` / `dislikes`—feeds **cold-start** logic in [src/recommender.py](src/recommender.py) (`_extract_movies_from_description`, `get_recommendations`). Established users are scored by **NMF** matrices loaded from `models/artifacts/model_nmf.joblib`; others fall through to **popularity** lists from `model_popularity.joblib` ([src/recommender.py](src/recommender.py) `_load_artifacts`, `joblib.load` at lines 48–53). The HTTP response is a **plain-text comma-separated list** of up to twenty movie keys. In parallel, **Kafka** `movielog2` events are appended by [src/kafka_collector.py](src/kafka_collector.py) into `raw_data/movielog_*.jsonl` and later participate in **scheduled retraining** ([scripts/retrain_and_deploy.sh](scripts/retrain_and_deploy.sh): `git pull`, bounded `timeout 300 python3 src/kafka_collector.py`, `train`/`deploy` steps). **Prometheus** scrapes `/metrics` on the API and the Kafka-backed exporter ([monitoring/prometheus.yml](monitoring/prometheus.yml)), with rules in [monitoring/alerts.yml](monitoring/alerts.yml).

**Where STRIDE was applied (evidence by pointer).** *Spoofing / tampering:* trust boundary at the User API client and at disk artifacts under `models/artifacts/`. *Repudiation:* experiment assignment logging via `get_manager().log_assignment` ([src/app.py](src/app.py) lines 169–171) partially attributes outcomes but does not cryptographically bind clients. *Information disclosure:* `/metrics` exposes counters and histograms ([src/app.py](src/app.py) `/metrics` route, lines 203–206); labels include `model_type`, derived from the recommender path. *Denial of service:* unauthenticated successful path still executes NMF inference and optional rerankers. *Elevation:* `git pull` and arbitrary `joblib` replacement on the VM effectively elevate any shell principal to control served behaviour ([scripts/retrain_and_deploy.sh](scripts/retrain_and_deploy.sh) Step 1, 55–59).

---

### Issue 1 — Infrastructure and operations exposure (general system security)

**Description.** The prediction API and its **Prometheus text exposition** are served from the same Flask process without an application-layer **authentication or authorization** gate on `/recommend/<userid>` or `/metrics` ([src/app.py](src/app.py)). Any network principal that can reach the host port therefore obtains **health, traffic shape, and per-request model-path labels** (`recommendation_requests_total{status=,model_type=}`), which supports **reconnaissance** and capacity planning for abuse. The stack assumes **perimeter security** (course VM firewall, grader-only access) rather than zero-trust micro-segmentation. Separately, the **retrain pipeline** performs `git pull --rebase origin main` before training ([scripts/retrain_and_deploy.sh](scripts/retrain_and_deploy.sh) lines 55–59), conflating **code integrity** with **model integrity**: a compromised upstream branch or credentialed `git` access on the VM becomes a **deployment tampering** channel. Kafka ingest uses `localhost:9092` ([src/kafka_collector.py](src/kafka_collector.py) lines 14–16), typically bridged by an **SSH tunnel**; tunnel or broker disruption is an **availability** risk rather than student write access to the broker, but misconfiguration can still leave **stale or partial** training corpora in `raw_data/`, weakening integrity guarantees for downstream NMF.

**Plausibility.** Course-style VMs are routinely port-scanned; `/metrics` is a standard Prometheus integration that is dangerous when exposed to untrusted networks. Shared-operator VMs with shell access are a textbook **insider threat** surface for both `git pull` and artifact replacement.

---

### Issue 2 — Attacks targeting the recommendation model (poisoning and output harvesting)

**Description.** Two ML-specific threats intersect our architecture.

First, **training-time poisoning / integrity attacks on learned weights.** NMF and popularity statistics are refit from **ingested interaction logs** and derived CSVs, then serialized with **`joblib`** into `models/artifacts/*.joblib` ([src/recommender.py](src/recommender.py) lines 48–53; retrain script backup and train steps in [scripts/retrain_and_deploy.sh](scripts/retrain_and_deploy.sh)). An adversary who can **append fabricated watch/rating-like records** to `raw_data/` or **swap joblib payloads** before the next worker reload causes **persistent model bias** or **backdoored responses** for chosen user cohorts—classic **data-poisoning** and **artifact substitution** against collaborative filters.

Second, **inference-time harvesting and inversion-style threats.** Because `/recommend/<userid>` returns **deterministic lists** for a given user state and the service accepts a large space of user IDs, a remote client can **automate queries** to reconstruct per-user preference vectors up to the information limit of twenty IDs per call. Combined with public catalog metadata ([metadata/movies.json](metadata/movies.json)), this enables **attribute inference** and coarse **membership inference** against the training corpus—attacks adjacent to **model inversion** and **extraction** in the ML security literature, even though we do not expose raw latent factors over HTTP.

**Plausibility.** Poisoning is constrained in the course by broker **read-only** policy for students, but **not** by VM-local file tampering or insider actions. Output harvesting requires only TCP reachability to `:8082`, matching public assignment threat models.

---

## Mitigating Security Issues

**Issue 1 (infrastructure / exposure).** Harden the **network trust boundary**: terminate TLS at a reverse proxy, enforce **mutual TLS or VPN** for administrative scrape paths, and **restrict `/metrics`** to RFC1918 loopback via bind address or sidecar pattern. Add **API keys or OAuth2 client credentials** for `/recommend` if graders can present tokens. For **Git integrity**, stop training directly off mutable `main` on the VM: pin training to **immutable CI artifacts** (digest-tagged container images or signed release tarballs) and verify **commit signatures** before `train`. For Kafka path, monitor tunnel health (already partially covered by `KafkaConsumerDisconnected` in [monitoring/alerts.yml](monitoring/alerts.yml)) and fail closed on ingest when the tunnel is absent.

**Issue 2 (model-targeted attacks).** Mitigate **poisoning** with **provenance and validation gates**: cryptographic hashes of `raw_data` shards recorded in `model_version.json`, anomaly caps on per-user watch velocity before CSV promotion, and **human review** of drift alerts before `SIGHUP` reload. Replace or wrap **`joblib.load`** with **read-only artifact mounts** for the gunicorn user and **verify hashes** at process start. Mitigate **harvesting** with **per-API-key rate limits**, **per-user query budgets**, and **strip internal labels** from any future client-visible headers; prefer **aggregated metrics** only inside Prometheus.

**Justified partial inaction for the course prototype.** Full OAuth stacks and HSM-backed signing are **disproportionate** to a closed grader environment if the teaching staff **explicitly require** an unauthenticated HTTP surface for autograding. In that case, **documented firewall rules**, **rotated Grafana credentials**, and **VM image snapshots** are acceptable **compensating controls**, provided the residual risk is acknowledged in writing (as here).

---

## Analysis of a Security Issue

**Scope.** We evaluated **Issue 2’s inference-time abuse hypothesis**—whether **automated probing** or **DoS-style load** against `/recommend/<userid>` is **observable** using production-style telemetry already instrumented in [src/app.py](src/app.py).

**Telemetry used.** Prometheus scrapes `recommendation_requests_total{status,model_type}`, `recommendation_errors_total{error_type}`, and `recommendation_latency_seconds` histograms from `/metrics` ([monitoring/prometheus.yml](monitoring/prometheus.yml) job `recommendation-service`). Alert thresholds operationalize “bad” behaviour (`HighErrorRate`, `HighLatency` in [monitoring/alerts.yml](monitoring/alerts.yml)). The Kafka exporter exposes **`online_rec_rate_per_minute`** as a **cross-check** between organic simulator traffic and raw HTTP load to the team API ([monitoring/metrics_exporter.py](monitoring/metrics_exporter.py)).

**Method.** (1) Confirm scrape targets reachable from Prometheus. (2) Execute **instant PromQL** via the Prometheus HTTP API for `sum(rate(recommendation_requests_total[1m]))`, `sum by (model_type)(rate(...))`, `sum(rate(recommendation_errors_total[1m]))`, and `histogram_quantile(0.95, …)` on latency buckets—mirroring dashboard panels. (3) Compare HTTP-side rates to `online_rec_rate_per_minute` to detect **HTTP-only bursts**. (4) Record whether `HighLatency` / `HighErrorRate` would have fired over the observation window.

**Findings.** During normal course operation we **did not** observe sustained error-rate or p95-latency excursions that would uniquely indicate an active **inference DoS** separate from legitimate grader bursts—an important **negative result** establishing a **benign baseline** when Prometheus had fresh samples. Conversely, metrics **lack client identity labels** (no IP, no API key), so a sudden spike in `recommendation_requests_total` **cannot be attributed** to a malicious scanner versus concurrent autograding: **attack non-attribution** is a second **negative finding** for forensic certainty, not for detection of volume anomalies.

**Ethical note.** We **declined** to run synthetic high-volume attacks against the shared grader endpoint; conclusions rest on **passive** monitoring and **offline notebook replay** on the VM.

**Additional negative result (distribution of outputs).** Because we do not log per-response movie IDs to Prometheus (only aggregate `recommendations_served_total` counts in [src/app.py](src/app.py)), telemetry **cannot** currently answer whether an adversary is **steering** outputs toward a fixed set of IDs—another **observability gap** relative to inversion-style hypotheses. Extending instrumentation with a **sampled, privacy-preserving** histogram of genre buckets (exporter-side, not per-user) would be required for that sub-question.

**Artifacts (repo-relative).**

- [notebooks/security_telemetry_analysis.ipynb](notebooks/security_telemetry_analysis.ipynb) — reproducible PromQL driver (`PROMETHEUS_URL` configurable).
- [src/app.py](src/app.py) — metric definitions and `/metrics` route.
- [monitoring/alerts.yml](monitoring/alerts.yml) — alert expressions used as benchmarks.
- [monitoring/metrics_exporter.py](monitoring/metrics_exporter.py) — Kafka-side online rate for comparison.
- [docs/SECURITY_REPORT.md](docs/SECURITY_REPORT.md) — standalone security + safety write-up (overlaps this milestone section).

**GitHub (`main`) — same artifacts for submission/PDF:**

- Telemetry notebook: [notebooks/security_telemetry_analysis.ipynb](https://github.com/cmu-seai/group-project-s26-model-impossible-1/blob/main/notebooks/security_telemetry_analysis.ipynb)
- Standalone report: [docs/SECURITY_REPORT.md](https://github.com/cmu-seai/group-project-s26-model-impossible-1/blob/main/docs/SECURITY_REPORT.md)
- Service metrics: [src/app.py](https://github.com/cmu-seai/group-project-s26-model-impossible-1/blob/main/src/app.py)
- Prometheus scrape config: [monitoring/prometheus.yml](https://github.com/cmu-seai/group-project-s26-model-impossible-1/blob/main/monitoring/prometheus.yml)
- Alert rules: [monitoring/alerts.yml](https://github.com/cmu-seai/group-project-s26-model-impossible-1/blob/main/monitoring/alerts.yml)
- Kafka / online metrics exporter: [monitoring/metrics_exporter.py](https://github.com/cmu-seai/group-project-s26-model-impossible-1/blob/main/monitoring/metrics_exporter.py)

**Evaluation checklist (rubric self-check).**

- [x] Security identification process described (STRIDE + data-flow trace).
- [x] Two security issues; Issue 2 is an ML-targeted attack (poisoning / harvesting–inversion adjacent).
- [x] Both issues plausible in deployment context.
- [x] Plausible mitigations (and justified partial inaction) for both.
- [x] Telemetry analysis clearly described with explicit positive/negative findings.

---

## Safety Risks

We scoped safety separately from fairness, feedback loops, and security. Here, safety means harms that can occur even when the recommender behaves as implemented, but without the policy or product guardrails a real streaming service would normally add.

We used a compact hazard-analysis workflow inspired by FMEA-style reasoning: function -> failure mode -> scenario -> harm. We first listed the main functions of our deployed slice, then asked what could go wrong when the output is wrong or the user context is missing, and finally traced those failures to real-world harms instead of only prediction-quality degradation.

1. Rank and return up to 20 movie IDs from collaborative filtering, popularity, or cold-start logic in [src/recommender.py](src/recommender.py).
2. Blend self-description signals with popularity fallback for new users in [src/recommender.py](src/recommender.py).
3. Periodically retrain and redeploy models through [scripts/retrain_and_deploy.sh](scripts/retrain_and_deploy.sh).
4. Expose system telemetry through the monitoring stack, whose outputs can influence operator actions.

Evidence that we followed this process is visible in the specific hazards below: they are tied to actual implementation details and metadata fields rather than generic brainstorming. In particular, the catalog contains an `adult` field in [metadata/movies.json](metadata/movies.json), but the serving path in [src/recommender.py](src/recommender.py) does not consult it when ranking recommendations.

**Safety issue A: psychological and trauma-related harm from ungated title lists.** The system returns movie IDs only and applies no content warnings, intensity caps, or user-vulnerability controls. A user in acute distress could therefore be recommended violent or assault-themed content purely because it ranks highly under collaborative or popularity-based signals. The real-world harm is not just poor personalization; it can be re-traumatization, acute anxiety, or sleep disruption caused by normal operation without editorial safeguards.

**Safety issue B: child and teen exposure when age context is absent.** The serving API has no age, household-profile, or parental-control input, and the cold-start plus popularity paths do not enforce age-aware filtering. A minor account, or a shared family account implicitly treated as adult, could therefore receive adult or developmentally inappropriate titles if those titles score well in the current recommender. The potential harm includes inappropriate exposure, parental conflict, and regulatory or reputational risk for a production operator.

---

## Mitigating Safety Issues

For the first safety issue, we would mitigate harm by adding policy and product controls above the ranking model rather than relying on the recommender alone. The most direct design change is to enrich the serving path with content-safety metadata and apply a post-ranking filter that can block or down-rank titles by content category, intensity, or explicit user preference. In a consumer product, we would also expose warnings or a "comfort mode" in the UI so users can opt out of distressing content even when the base recommender would otherwise surface it.

For the second safety issue, the core mitigation is to make age context explicit in the serving contract and to fail safe when that context is missing. In practice, that means adding an age-band or household-profile signal to the recommendation request, maintaining kid-safe or teen-safe policy tiers, and defaulting unknown-age users to the most restrictive policy rather than the least restrictive one. We would also add a pre-deploy operational gate to the retraining or release process that runs the safety analysis in [scripts/safety_analysis.py](scripts/safety_analysis.py) and blocks a rollout if exposure of minors to `adult=true` titles crosses a threshold. This is intentionally a process and monitoring change, not only a model change, because the rubric asks for plausible system or development-practice mitigations.

---

## Analysis of a Safety Issue

We analyzed safety issue B, child and teen exposure to adult titles, using the telemetry and metadata already present in the repository. The concrete question was: do under-18 users receive recommendations containing titles marked `adult=true`, and if so, how often?

**Method.** We implemented the analysis in [src/analysis/safety.py](src/analysis/safety.py) with a CLI wrapper in [scripts/safety_analysis.py](scripts/safety_analysis.py). The analysis loads recommendation events from [experiments/logs/exp_cold_start.jsonl](experiments/logs/exp_cold_start.jsonl) and [experiments/logs/exp_cost_optimise.jsonl](experiments/logs/exp_cost_optimise.jsonl), joins each event with user age from [metadata/users.json](metadata/users.json), restricts the sample to users with `age < 18`, and then joins each recommended movie ID with the `adult` field in [metadata/movies.json](metadata/movies.json). The saved artifact is [experiments/results/m4_safety.json](experiments/results/m4_safety.json).

**Metric.** Our primary metric is `minor_adult_recommendation_rate`: the fraction of recommendation events for users under 18 that contain at least one `adult=true` title. We also compute `minor_adult_title_share`, the share of recommended titles shown to under-18 users that are marked adult.

**Results.** The local run scanned 1002 recommendation events in total and found 8 recommendation events for under-18 users spanning 4 unique minors. Across those 8 events, we observed 0 events containing any `adult=true` title and 0 adult titles among 160 recommended titles shown to minors. This yielded `minor_adult_recommendation_rate = 0.0` and `minor_adult_title_share = 0.0`, with the saved conclusion `no_observed_harm_in_sample` in [experiments/results/m4_safety.json](experiments/results/m4_safety.json).

This is a negative result, not proof that the system is safe. The main limitation is sample size: only 8 minor recommendation events were available in the local telemetry slice, and we did not have local watch-shard data to measure whether any risky exposures were later watched. Still, the analysis satisfies the audit requirement because it uses actual system telemetry, clearly defines the metric and computation, and reports the observed result, including the negative finding and its limitations.

---

## Team contract update

*No update to team contract.*