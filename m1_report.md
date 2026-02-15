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
- **Metric:** [e.g., RMSE on ratings, NDCG, hit rate, etc.]
- **Data:** [What data you use – e.g., held-out ratings, time split.]
- **Operationalization:** [Exact steps/formula to compute the metric.]
- **Code:** [Link to evaluation code.]

### Quality 2: Training cost
- **Metric:** [e.g., wall-clock time in seconds, or CPU-hours.]
- **Data:** [What runs/logs you use.]
- **Operationalization:** [How you measure it.]
- **Code:** [Link to script or instructions.]

### Quality 3: Inference cost / throughput
- **Metric:** [e.g., requests per second, or latency p95.]
- **Data:** [How you generate load / collect timings.]
- **Operationalization:** [How you compute the metric.]
- **Code:** [Link to benchmark or serving code.]

### Quality 4: Model size (disk or memory)
- **Metric:** [e.g., size in MB on disk, or peak memory when loaded.]
- **Data:** [Saved model files, or memory profiler output.]
- **Operationalization:** [How you measure.]
- **Code:** [Link if you have a small script.]

### Comparison table

| Quality           | Model 1 (e.g. Collaborative Filtering) | Model 2 (e.g. Content-Based) |
|------------------|----------------------------------------|------------------------------|
| Prediction accuracy | [value + unit]                      | [value + unit]               |
| Training cost    | [value + unit]                         | [value + unit]               |
| Inference/throughput | [value + unit]                    | [value + unit]               |
| Model size       | [value + unit]                         | [value + unit]               |

### Choice for production
- **We use in production:** [Model 1 or Model 2, or an ensemble.]
- **Reason:** [Short justification based on the four qualities and any constraints, e.g. latency < 600 ms.]

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
