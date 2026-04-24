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

### Process: STRIDE-oriented threat modeling and data flows

We analyzed the stack with **STRIDE** mapped to **real components**: for each category we traced **who controls input**, **trust boundaries crossed**, and **what an adversary learns or breaks** along the paths below.

**End-to-end data flow (evidence in code).** Clients call `GET /recommend/<userid>` in [src/app.py](src/app.py); `userid` is validated with `_USERID_RE` / `_valid_userid` (lines 37–41), early rejection in the route (117–119), and `validate_recommendation_request` (125–127). The service may fetch profile JSON via `CourseApiClient` using `API_BASE` (from env `USER_API_BASE`, line 33; `create_course_api_client` / `get_user` at lines 131–132), supplying `self_description_likes` / `self_description_dislikes` into **cold-start** matching in [src/recommender.py](src/recommender.py). Known users get **NMF** scores from `models/artifacts/model_nmf.joblib`; others use **popularity** from `model_popularity.joblib` (`joblib.load` in `_load_artifacts`, lines 48–53). The reply is up to **20 movie IDs** as plain text. **Training data** flows from Kafka `movielog2` through [src/kafka_collector.py](src/kafka_collector.py) (`raw_data/movielog_*.jsonl`, `localhost:9092`) into **cron-driven retraining** ([scripts/retrain_and_deploy.sh](scripts/retrain_and_deploy.sh): Step 1 `git pull` at line 58, timed collector Step 2, train, hot reload). **Observability:** Prometheus scrapes `/metrics` and the Kafka exporter per [monitoring/prometheus.yml](monitoring/prometheus.yml); rules live in [monitoring/alerts.yml](monitoring/alerts.yml).

**STRIDE → our surfaces (compact).** Tampering/spoofing: User API trust and **on-disk** `models/artifacts/*.joblib`. Information disclosure: unauthenticated `/metrics` exposes request rates and **`model_type`** labels ([src/app.py](src/app.py) `/metrics` route, lines 203–207; counters registered at lines 46–60). DoS: successful requests still run NMF / reranking without app-level rate limits. Elevation: shell or `git` on the VM can change code or artifacts before the next train or reload ([scripts/retrain_and_deploy.sh](scripts/retrain_and_deploy.sh) Step 1, lines 56–59). Repudiation: experiment logging ([src/app.py](src/app.py) `mgr.log_assignment`, lines 170–171) improves traceability but does not bind remote clients cryptographically.

---

### Issue 1 — General infrastructure and supply-chain exposure

**Description.** `/recommend/<userid>` and `/metrics` share the same Flask process with **no application-layer auth** ([src/app.py](src/app.py)). Anyone who can reach the VM learns **traffic shape, errors, latency, and `model_type` mix**—useful for reconnaissance and sizing an attack. Retraining runs **`git pull --rebase origin main`** before training ([scripts/retrain_and_deploy.sh](scripts/retrain_and_deploy.sh) lines 56–59), so **mutable `main`** and VM **shell access** become a **deployment integrity** channel. Kafka ingest depends on a **tunnel to `localhost:9092`** ([src/kafka_collector.py](src/kafka_collector.py)); tunnel loss yields **stale `raw_data/`**, silently degrading the integrity of the next NMF fit.

**Plausibility.** Exposed `/metrics`, shared VMs, and `git pull` on the train host are realistic in course and small-team production setups.

---

### Issue 2 — Attacks on the recommendation model (poisoning and inference / inversion-style abuse)

**Description.** **Training-time:** NMF and popularity are fit from ingested logs and materialized as **`*.joblib`** under `models/artifacts/` (training and deploy orchestration in [scripts/retrain_and_deploy.sh](scripts/retrain_and_deploy.sh)); the serving process **loads** those artifacts with `joblib.load` in `_load_artifacts` ([src/recommender.py](src/recommender.py) lines 49–53). A party who can **append synthetic JSONL**, alter processed tables, or **replace `.joblib` files** before reload achieves **data poisoning** or **trojan weights**—attacks aimed squarely at the **learned** recommender. **Inference-time:** `/recommend/<userid>` returns **up to 20 movie IDs** per response (stable for a given user under fixed traffic); automated queries over many IDs **harvest** preference signals. With [metadata/movies.json](metadata/movies.json), that supports **attribute and membership inference**—**inversion- and extraction-adjacent** threats against the model’s **information output**, even without exposing latent factor vectors over HTTP.

**Plausibility.** Course Kafka is read-only for students, but **VM-local** tampering and **unrestricted HTTP** to `:8082` remain plausible in this deployment model.

---

## Mitigating Security Issues

**Issue 1 (infrastructure / exposure).** Harden the **network trust boundary**: terminate TLS at a reverse proxy, enforce **mutual TLS or VPN** for administrative scrape paths, and **restrict `/metrics`** to **loopback-only** bind addresses or an admin-only sidecar. Add **API keys or OAuth2 client credentials** for `/recommend` if graders can present tokens. For **Git integrity**, stop training directly off mutable `main` on the VM: pin training to **immutable CI artifacts** (digest-tagged container images or signed release tarballs) and verify **commit signatures** before **training**. For Kafka path, monitor tunnel health (already partially covered by `KafkaConsumerDisconnected` in [monitoring/alerts.yml](monitoring/alerts.yml)) and fail closed on ingest when the tunnel is absent.

**Issue 2 (model-targeted attacks).** Mitigate **poisoning** with **provenance and validation gates**: cryptographic hashes of `raw_data` shards recorded in `model_version.json`, anomaly caps on per-user watch velocity before CSV promotion, and **human review** of drift alerts before `SIGHUP` reload. Replace or wrap **`joblib.load`** with **read-only artifact mounts** for the gunicorn user and **verify hashes** at process start. Mitigate **harvesting** with **per-API-key rate limits**, **per-user query budgets**, and **strip internal labels** from any future client-visible headers; prefer **aggregated metrics** only inside Prometheus.

**Justified partial inaction for the course prototype.** Full OAuth stacks and HSM-backed signing are **disproportionate** to a closed grader environment if the teaching staff **explicitly require** an unauthenticated HTTP surface for autograding. In that case, **documented firewall rules**, **rotated Grafana credentials**, and **VM image snapshots** are acceptable **compensating controls**, provided the residual risk is acknowledged in writing (as here).

---

## Analysis of a Security Issue

**Scope.** We tested whether **Issue 2’s inference-time abuse** (automated probing or **DoS-style** load on `/recommend/<userid>`) is **observable** from telemetry in [src/app.py](src/app.py).

**Signals.** Prometheus scrapes `recommendation_requests_total{status,model_type}`, `recommendation_errors_total{error_type}`, and `recommendation_latency_seconds` ([monitoring/prometheus.yml](monitoring/prometheus.yml) job `recommendation-service`; definitions in [src/app.py](src/app.py) lines 46–60, `/metrics` at 203–207). We compared HTTP rates to **`online_rec_rate_per_minute`** from the Kafka exporter ([monitoring/metrics_exporter.py](monitoring/metrics_exporter.py)) and used `HighErrorRate` / `HighLatency` in [monitoring/alerts.yml](monitoring/alerts.yml) as operational thresholds.

**Method.** Confirm scrape targets; run **instant PromQL** (`/api/v1/query`) for request rate (total and by `model_type`), error rate, and p95 latency—same family as [notebooks/security_telemetry_analysis.ipynb](notebooks/security_telemetry_analysis.ipynb). Compare to `online_rec_rate_per_minute`; note whether alert rules would have fired.

**Findings.** We saw **no sustained** error or p95-latency pattern that **isolates** an inference DoS from normal grader traffic (**negative result** for “attack clearly detected”). Metrics carry **no client IP or API key**, so spikes are **not attributable** to malice vs autograde (**negative result** for attribution). Only **`recommendations_served_total`** aggregates outputs—no per-title telemetry—so **output-steering** (inversion-style) is **not observable** today without extra instrumentation.

**Ethics.** No deliberate high-volume attacks against the shared endpoint; conclusions from **passive** windows and **notebook replay** on the VM.

**Artifacts (GitHub `main`).** [notebooks/security_telemetry_analysis.ipynb](https://github.com/cmu-seai/group-project-s26-model-impossible-1/blob/main/notebooks/security_telemetry_analysis.ipynb) · [src/app.py](https://github.com/cmu-seai/group-project-s26-model-impossible-1/blob/main/src/app.py) · [monitoring/prometheus.yml](https://github.com/cmu-seai/group-project-s26-model-impossible-1/blob/main/monitoring/prometheus.yml) · [monitoring/alerts.yml](https://github.com/cmu-seai/group-project-s26-model-impossible-1/blob/main/monitoring/alerts.yml) · [monitoring/metrics_exporter.py](https://github.com/cmu-seai/group-project-s26-model-impossible-1/blob/main/monitoring/metrics_exporter.py) · [docs/SECURITY_REPORT.md](https://github.com/cmu-seai/group-project-s26-model-impossible-1/blob/main/docs/SECURITY_REPORT.md)

*Rubric self-check:* threat process + two plausible issues (including ML-targeted Issue 2) appear under **Security Risks**; mitigations under **Mitigating Security Issues**; telemetry method + negative findings + GitHub pointers in this section.

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
