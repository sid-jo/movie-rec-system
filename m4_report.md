# Milestone 4 Report: Fairness, Security, and Feedback Loops

**Repository:** [cmu-seai/group-project-s26-model-impossible-1](https://github.com/cmu-seai/group-project-s26-model-impossible-1)

This report matches the implementation on `main`. All code, notebooks, and artifacts referenced below are linked relative to the repo root. Numbers in `[brackets]` are filled by the analysis scripts and updated on each run.

---

## Fairness Risks

We followed a five-step fairness analysis process. Intermediate artifacts are committed in [docs/fairness/](docs/fairness/) (harm table, bias-source notes, conflict matrix); the findings below summarise them.

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
Measure: per-group mean rating and per-user-mean-watch-count with Wilson 95% CIs and a two-sample Welch *t*-test;
[src/analysis/fairness.py::group_engagement](src/analysis/fairness.py).

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

**R2 is clearly violated across the entire non-English catalog**, not just a few edge cases. English titles are 85 % of the catalog but capture 95 % of plays (ratio 1.12×), while Finnish, Norwegian and Hindi films see less than 10 % of their neutrally-expected share. Because plays in our system are almost entirely driven by what we recommend (the simulator's users click recs rather than searching), this distribution is a direct downstream signature of the recommender's output.

The mechanism is structural and traceable in our code:

- The **popularity fallback** ([src/recommender.py:156-163](src/recommender.py#L156-L163)) returns a hash-shifted slice of `_top_movies` — itself learned from historically English-heavy watch counts — for every low-signal user.
- The **cold-start extraction** ([src/recommender.py:58-70](src/recommender.py#L58-L70)) can only match titles users wrote in English against English-normalised catalog keys.
- The **hardcoded fallback list** at [src/recommender.py:169-180](src/recommender.py#L169-L180) is 10 English titles.
- The **3-day retrain cron** ([scripts/retrain_and_deploy.sh](scripts/retrain_and_deploy.sh)) feeds today's English-skewed watches back into tomorrow's `_top_movies`, amplifying the bias with every cycle.

The measurement is indirect (we observe watches, not recommendations) because the raw-log dump contains no `recommendation request` events. Stratifying the same metric by `model_type` (already logged on each rec event in Prometheus) will sharpen the attribution once rec-event telemetry is being collected — this is captured as an R2-adjacent improvement in the mitigation section.

---

## Anticipating Feedback Loops

*TODO — fill during the feedback-loop track.*

## Mitigating a Negative Feedback Loop

*TODO*

## Analysis of a Feedback Loop

*TODO* 

---

## Security Risks

*TODO* 

## Mitigating Security Issues

*TODO*

## Analysis of a Security Issue

*TODO* 

---

## Safety Risks

*TODO* 

## Mitigating Safety Issues

*TODO*

## Analysis of a Safety Issue

*TODO* 

---

## Team contract update

*No update to team contract.*