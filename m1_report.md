# Milestone 1 Report: Recommendation Model and First Deployment

## 1. Learning 

### Data and techniques
- **Data used:** We constructed our dataset by aggregating three primary sources:
    * **Kafka Event Stream:** We ingested the `movielog2` topic to capture real-time user interactions, specifically filtering for `GET /data/m/...` (watch events) and `GET /rate/...` (explicit ratings). This provided our core user-item interaction matrix.
    * **User API:** We queried user metadata (`/user/<id>`) to retrieve demographic information and, critically, the **self-described tags** (interests) to assist with new users.
    * **Movie API:** We enriched our item data by querying `/movie/<id>` to map movie IDs to genres and titles, enabling content-based matching.

- **ML technique(s):** We implemented **Collaborative Filtering using SVD (Matrix Factorization)** as our primary model to capture latent user preferences. For the cold-start problem, we utilized a **Content-Based Filtering** approach mapping user tags to movie genres.
- **Why this approach:** SVD was chosen for its computational efficiency and ability to handle the high sparsity of our initial dataset while still providing personalized results. The Content-Based approach was selected to leverage the static user metadata (self-described tags) available immediately upon user signup, ensuring we can serve relevant recommendations before any watch history exists.

### Cold-start problem
- **How we address cold start:** When a request arrives for a user with no history in our Kafka logs, we query the User API for their `self-described tags`. We match these tags against our Movie API metadata (genres/keywords) to filter and rank movies. If no tags are present, we fall back to a global popularity baseline.
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
- **Stack:** Flask serving a Python-based inference engine, deployed on the team VM.
- **Endpoint:** `http://128.2.220.243:8082/recommend/<userid>`
- **Response Format:** Returns a single line of up to 20 comma-separated **movie IDs**, highest to lowest recommendation.
- **How ranking is derived:** 
    1. Check if User ID exists in the SVD latent matrix.
    2. **If yes:** Predict ratings for unstopped movies, sort by score descending, take top 20.
    3. **If no (Cold Start):** Fetch User Tags -> Match with Movie Genres -> Sort by Popularity within Genre -> Take top 20.
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
