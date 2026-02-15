# Milestone 1 Report: Recommendation Model and First Deployment

## 1. Learning 

### Data and techniques
- **Data used:** [Describe what data you use: Kafka stream events, user API, movie API, ratings, watches, user self-descriptions, etc.]
- **ML technique(s):** [e.g., collaborative filtering, content-based, matrix factorization, cold-start approach.]
- **Why this approach:** [Brief justification for data and technique choices.]

### Cold-start problem
- **How we address cold start:** [Describe how you use users' self-described "likes" and "dislikes" (and any other signals) for new users with no history.]
- **Implementation:** [Pointer to code – e.g., `models/cold_start.py`, `notebooks/...`, or GitHub path.]

### Training at least two models
- **Model 1:** [Name and short description.]
- **Model 2:** [Name and short description.]
- **Pointer to implementation:** [Link to repo/path where you train both models, e.g. `models/train_models.py`.]

---

## 2. Model Comparison 

For each quality, define a measure in **three steps**: (1) metric, (2) data gathered, (3) operationalization (how you compute the measure from the data). Descriptions should be precise enough for someone to reimplement without your code.

### Quality 1: Prediction accuracy
- **Metric:** NDCG@20 (Normalized Discounted Cumulative Gain at rank 20)
- **Data:** Test set – 200 users with 10+ ratings; for each user, movies rated 7+ (on 1–10 scale) as relevant items
- **Operationalization:** For each test user, generate top 20 recommendations; compute DCG = sum(1/log2(position+1)) for relevant items in recommendations; compute IDCG for ideal ordering; NDCG = DCG/IDCG; average across users
- **Code:** [models/evaluate_models.py](models/evaluate_models.py) (`evaluate_accuracy`, `calculate_ndcg_at_k`)

### Quality 2: Training cost
- **Metric:** Wall-clock time in seconds
- **Data:** Time captured during `model.fit()` in `models/train_models.py`
- **Operationalization:** Call `time.time()` before and after each model’s `fit()`; record elapsed seconds; store in `training_metadata.json`
- **Code:** [models/train_models.py](models/train_models.py), [models/saved/training_metadata.json](models/saved/training_metadata.json)

### Quality 3: Inference cost / throughput
- **Metric:** Average latency in milliseconds per recommendation request
- **Data:** 1000 prediction calls on random users from training data
- **Operationalization:** For each user, call `time.perf_counter()` before and after `model.predict(user_id, top_k=20)`; convert to ms; report mean
- **Code:** [models/evaluate_models.py](models/evaluate_models.py) (`evaluate_inference_cost`)

### Quality 4: Model size (disk or memory)
- **Metric:** Disk size in megabytes of serialized model file
- **Data:** Size of `.pkl` model files on disk
- **Operationalization:** `os.path.getsize(model_path)` in bytes; divide by 1024×1024
- **Code:** [models/evaluate_models.py](models/evaluate_models.py) (`evaluate_model_size`)

### Comparison table

| Quality              | Collaborative Filtering | Content-Based |
|----------------------|-------------------------|---------------|
| Prediction accuracy  | 0.0000 (NDCG@20)        | 0.0450 (NDCG@20) |
| Training cost        | 47.58 s                 | 20.59 s |
| Inference/throughput | 9.82 ms avg             | 28.62 ms avg |
| Model size           | 4307.14 MB              | 3.97 MB |

### Choice for production
- **We use in production:** Content-Based (Genre Matching)
- **Reason:** Both models meet the 600 ms latency requirement (9.82 ms and 28.62 ms respectively). We choose Content-Based because: (1) better accuracy (NDCG@20 0.045 vs 0); (2) much smaller model size (3.97 MB vs 4307 MB), enabling easier deployment; (3) faster training (20.59 s vs 47.58 s); (4) inference at 28.62 ms leaves ample headroom under 600 ms.

---

## 3. Prediction Service 

### Implementation
- **Stack:** [e.g., Flask on port 8082, gunicorn, etc.]
- **Endpoint:** `GET /recommend/<userid>` → single line: up to 20 comma-separated **movie IDs**, highest to lowest recommendation.
- **How ranking is derived:** [How you go from your model(s) to an ordered list of movie IDs – e.g., scores from CF, then merge with cold-start for new users.]

### Pointers to implementation
- **Model training:** [Link to repo path, e.g. `models/train_models.py`.]
- **Serving / ranking:** [Link to repo path, e.g. `src/app.py` and any helper that builds the list of movie IDs.]

---

## 4. Team Contract and Meeting Notes 

### 4.1 Communication
- **Channels:** Slack for daily updates; Google Meet for weekly syncs.
- **Response expectations:** Team members are expected to respond to messages within 12 hours on weekdays.
- **Norms:** Members must be punctual, communicate delays, and deliver high-quality work on schedule.
- **Teamwork:** We will divide tasks equally, listen to all perspectives, and address conflicts early and amicably.

### 4.2 Project and team management
- **Time commitment:** Each member commits to a minimum of 8 hours per week, with the expectation that this will scale up during peak deployment phases. This baseline ensures steady progress while remaining flexible for the project's increasing complexity later in the semester.
- **Management:** Note-taking and facilitation roles will rotate weekly or be assigned based on natural fit.
- **Organization:** All notes and documentation will be centralized in a shared Google Drive for easy team and instructor access.
- **Tracking unresponsive members:** Barath will be responsible for tracking down ghosting teammates.

### 4.3 Dividing work and assigning responsibilities
- **Process:** Work is divided into functional modules (Infrastructure, Modeling, Deployment). We assign owners to each based on interest and bandwidth during our weekly syncs.

### 4.4 If someone is unresponsive or has problems/delays
- **Process:** Members must review assignment details before meetings. Recurring absences will trigger a formal conflict resolution process to ensure everyone stays on track. If a member is unresponsive for 24 hours, the project lead will reach out via phone; if issues persist, we will contact our team mentor immediately to redistribute tasks.

### 4.5 Other agreements
- All code must be reviewed via Pull Request by at least one other member before merging.
- We agree to a "no-blame" culture where blockers are flagged early without judgment.

**Signatures:** Ryan Wang, Tianyue Yin, Siddhant Joshi, Barath, Sai Chittamuru

- **Team agreement (full contract):** [Team Agreement](https://docs.google.com/document/d/1T4b6xQDmIn3bMxo4N0otmVa8lHr9dg27xHuMbu_vZKg/edit?tab=t.0)

### 4.6 M1 work division (who / what / when)
- **Meeting notes (who / what / when):** [Meeting Notes](https://docs.google.com/document/d/1Lehml4IPtNqlVQrwD13PerG-XOPJxZtDCWOLvMOf-Q4/edit?tab=t.0)
- **Summary:** For this milestone, *who* was responsible for *what*, by *when* — see the meeting notes link above for the full breakdown.
