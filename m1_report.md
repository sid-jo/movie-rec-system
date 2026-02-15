# Milestone 1 Report: Recommendation Model and First Deployment

## 1. Learning 

### Data and techniques
- **Data used:** 
  - **Kafka stream events**: We collect event logs from the course Kafka stream (`movielog2` topic) which includes:
    - Rating events: `GET /rate/<movieid>=<rating>` (ratings on 1-10 scale)
    - Watch events: `GET /data/m/<movieid>/<minute>.mpg` (movie viewing behavior)
    - Recommendation requests: logs showing which recommendations were served
    - Account creation events: `GET /create_account` (new user signups)
  - **User API** (`http://128.2.220.241:8080/user/<id>`): Provides user metadata including:
    - User demographics (age, gender)
    - Self-described "likes" and "dislikes" text fields from signup
    - Other user attributes
  - **Movie API** (`http://128.2.220.241:8080/movie/<id>`): Provides movie metadata including:
    - Movie titles and genres (from TMDB)
    - Release years
    - License costs
    - IMDB and TMDB IDs
  - **Processed training data**: 
    - `data/processed/ratings.csv`: 210,038 ratings from 20,067 users across 10,676 movies
    - `data/processed/watches.csv`: 300,482 watch events tracking viewing behavior
  - **Metadata files**:
    - `metadata/users.json`: 20,067 user records with preferences
    - `metadata/movies.json`: 10,676 movie records with genre and feature information

- **ML technique(s):** 
  - **Model 1: Collaborative Filtering (User-User Similarity)**
    - Builds a user-item rating matrix where rows represent users and columns represent movies
    - Computes cosine similarity between users based on their rating patterns
    - For recommendations: finds similar users who rated movies highly (≥7.0 on 1-10 scale) and recommends those movies to the target user
    - Implementation: [`models/collaborative_filtering.py`](models/collaborative_filtering.py)
  
  - **Model 2: Content-Based Filtering**
    - Builds user genre preference profiles from highly-rated movies (rating ≥7.0)
    - Scores all movies based on genre match with user preferences, popularity (watch counts), and recency (movie age)
    - Uses weighted scoring: 60% genre match, 25% popularity, 15% recency
    - Implementation: [`models/content_based.py`](models/content_based.py)

- **Why this approach:** 
  - **Collaborative Filtering** captures user preferences through similarity patterns, leveraging the "wisdom of the crowd" to find movies liked by similar users. This works well when users have sufficient rating history.
  - **Content-Based Filtering** handles sparse data better by using movie features (genres) rather than requiring extensive user overlap. It also provides more explainable recommendations and can work for users with limited interaction history.
  - Together, these approaches provide complementary strengths: CF for users with rich history, and content-based for users with sparse data or when cold-start is needed.

### Cold-start problem
- **How we address cold start:** 
  We use the `ColdStartHandler` class to handle new users with no rating or watch history. The approach works as follows:
  
  1. **Parse user preferences**: When a new user signs up, they may provide free-text descriptions of movies they like and dislike in the "likes" and "dislikes" fields of their user profile.
  
  2. **Extract movie mentions**: The handler searches the user's text for mentions of known movie titles by normalizing titles (lowercase, remove special characters, remove "the/a/an" prefixes) and matching against our movie database.
  
  3. **Extract genre preferences**: 
     - From mentioned movies: extracts genres of movies the user explicitly mentioned
     - From text keywords: looks for direct genre mentions (e.g., "action movies", "comedies", "sci-fi")
     - Builds a set of preferred genres and disliked genres
  
  4. **Generate recommendations**:
     - Collects candidate movies from preferred genres
     - Filters out movies from disliked genres
     - Removes explicitly disliked movies
     - Scores candidates by popularity (watch count) and returns top 20
     - Falls back to most popular movies overall if no preferences are found
  
  This approach leverages the user's self-described preferences to make personalized recommendations even before they have any viewing history.

- **Implementation:** [`models/cold_start.py`](models/cold_start.py) - The `ColdStartHandler` class implements the full cold-start logic with methods `predict_for_new_user()`, `_find_mentioned_movies()`, and `_extract_genres_from_text()`.

### Training at least two models
- **Model 1: Collaborative Filtering (User-User Similarity)**
  - Builds a user-item rating matrix from historical ratings
  - Computes pairwise cosine similarity between all users
  - Uses top 50 most similar users for recommendations
  - Requires minimum 5 common rated items for similarity calculation
  - Trained on 210,038 ratings from 20,067 users

- **Model 2: Content-Based (Genre Matching)**
  - Builds user genre preference profiles from highly-rated movies (rating ≥7.0)
  - Indexes all movies with genre, popularity, and release year features
  - Scores movies using weighted combination: 60% genre match, 25% popularity, 15% recency
  - Trained on same rating data plus watch data for popularity calculation

- **Pointer to implementation:** [`models/train_models.py`](models/train_models.py) - This script loads processed data, trains both models sequentially, trains the cold-start handler, and saves all models to `models/saved/` directory. Training metadata (times, data stats) is saved to `models/saved/training_metadata.json`.

---

## 2. Model Comparison 

For each quality, define a measure in **three steps**: (1) metric, (2) data gathered, (3) operationalization (how you compute the measure from the data). Descriptions should be precise enough for someone to reimplement without your code.

### Quality 1: Prediction accuracy
- **Metric:** NDCG@20 (Normalized Discounted Cumulative Gain at rank 20) - a ranking quality metric that measures how well the top 20 recommendations match user preferences, with higher positions weighted more heavily.

- **Data:** 
  - Test set: 200 randomly sampled users from the training data who have at least 10 ratings
  - For each test user, movies rated ≥7.0 (on 1-10 scale) are considered "relevant" items
  - The model generates top 20 recommendations for each test user

- **Operationalization:** 
  1. For each test user, identify their relevant items (highly-rated movies, rating ≥7.0)
  2. Generate top 20 recommendations from the model
  3. Calculate DCG (Discounted Cumulative Gain): DCG = Σ(relevance / log₂(position + 1)) for positions 1-20, where relevance = 1 if the recommended movie is in the relevant set, 0 otherwise
  4. Calculate IDCG (Ideal DCG): the maximum possible DCG if all relevant items were ranked first: IDCG = Σ(1 / log₂(i + 2)) for i = 0 to min(num_relevant, 20) - 1
  5. NDCG = DCG / IDCG (normalized to 0-1 range)
  6. Average NDCG across all test users to get final metric

- **Code:** [`models/evaluate_models.py`](models/evaluate_models.py) - Functions `evaluate_accuracy()` (lines 73-140) and `calculate_ndcg_at_k()` (lines 42-70) implement this metric.

### Quality 2: Training cost
- **Metric:** Wall-clock time in seconds - the total elapsed time from start to completion of model training.

- **Data:** 
  - Time measurements captured during model training execution
  - Recorded separately for each model (Collaborative Filtering and Content-Based)
  - Stored in `models/saved/training_metadata.json` after training completes

- **Operationalization:** 
  1. Record system time using `time.time()` immediately before calling `model.fit()`
  2. Record system time immediately after `model.fit()` completes
  3. Compute difference: `training_time = end_time - start_time`
  4. Round to 2 decimal places and store in seconds
  5. Report training time for each model separately

- **Code:** [`models/train_models.py`](models/train_models.py) - Training time is measured at lines 53-55 (Collaborative Filtering) and lines 65-67 (Content-Based), then saved to metadata at lines 90-114.

### Quality 3: Inference cost / throughput
- **Metric:** Average latency per prediction in milliseconds - the mean time required to generate 20 recommendations for a single user.

- **Data:** 
  - 1000 prediction calls on randomly sampled user IDs from the training data
  - Each prediction call generates top 20 recommendations
  - Timing data collected for each individual prediction call

- **Operationalization:** 
  1. Randomly sample 1000 user IDs from the set of users in training data
  2. For each user ID:
     - Record system time using `time.time()` before calling `model.predict(user_id, top_k=20)`
     - Record system time immediately after prediction completes
     - Compute latency: `latency_ms = (end_time - start_time) * 1000` (convert to milliseconds)
     - Store latency value
  3. Compute statistics from collected latencies:
     - Mean: average of all latency values
     - P95: 95th percentile latency
     - P99: 99th percentile latency
  4. Report mean latency as the primary metric

- **Code:** [`models/evaluate_models.py`](models/evaluate_models.py) - Function `evaluate_inference_cost()` (lines 143-190) implements this measurement.

### Quality 4: Model size (disk or memory)
- **Metric:** Disk space in megabytes - the size of the serialized model file stored on disk.

- **Data:** 
  - Serialized model files saved as pickle (.pkl) files
  - Collaborative Filtering model: `models/saved/cf_model.pkl`
  - Content-Based model: `models/saved/cb_model.pkl`

- **Operationalization:** 
  1. Use `os.path.getsize(model_path)` to get file size in bytes
  2. Convert bytes to megabytes: `size_mb = size_bytes / (1024 * 1024)`
  3. Round to 2 decimal places
  4. Report size in MB for each model file separately

- **Code:** [`models/evaluate_models.py`](models/evaluate_models.py) - Function `evaluate_model_size()` (lines 193-214) implements this measurement.

### Comparison table

| Quality           | Collaborative Filtering | Content-Based |
|------------------|-------------------------|---------------|
| Prediction accuracy (NDCG@20) | 0.0000 | 0.0450 |
| Training cost (seconds) | 18.82 | 13.79 |
| Inference/throughput (avg ms) | 6.05 | 23.0 |
| Model size (MB) | 4307.14 | 3.97 |



### Choice for production
- **We use in production:** Content-Based Model

- **Reason:** 
  While the Collaborative Filtering model has faster inference (6.05ms vs 23.0ms), we choose the Content-Based model for production based on the following considerations:
  
  1. **Model size**: The Content-Based model is dramatically smaller (3.97 MB vs 4307.14 MB), making it much easier to deploy, version, and manage in production.
  
  2. **Training efficiency**: Content-Based trains faster (13.79s vs 18.82s), enabling more frequent model updates.
  
  3. **Inference latency**: At 23.0ms average latency, the Content-Based model is well below the 600ms requirement, providing ample headroom for API overhead and network latency.
  
  4. **Accuracy signal**: The Collaborative Filtering model shows 0.0000 NDCG@20, suggesting it may not be working correctly for the test set (possibly due to data sparsity or implementation issues). The Content-Based model shows measurable signal (0.0450 NDCG@20), indicating it is functioning and can be improved.
  
  5. **Cold-start capability**: The Content-Based approach aligns better with our cold-start strategy, as both rely on genre preferences, enabling a more unified recommendation pipeline.
  
  The 23ms inference time is acceptable given the 600ms constraint, and the massive reduction in model size (99.9% smaller) significantly simplifies deployment and operations.

---

## 3. Prediction Service 

### Implementation
- **Stack:** Flask application running on port 8082, accessible at `http://0.0.0.0:8082` (or `http://<VM-address>:8082` for production).

- **Endpoint:** `GET /recommend/<userid>` → returns a single line with up to 20 comma-separated **movie IDs** (not titles, not JSON), ordered from highest to lowest recommendation score.

- **How ranking is derived:** 
  
  **Current Implementation Status**: The API endpoint [`src/app.py`](src/app.py) is currently a placeholder implementation that:
  - Fetches user data from the course API (`http://128.2.220.241:8080/user/<userid>`)
  - Returns hardcoded recommendations based on user gender (for testing purposes)
  - Does NOT yet load or use the trained models
  
  **Intended Ranking Logic** (to be fully implemented):
  
  1. **Model Loading**: At application startup, load the trained models:
     - Content-Based model from `models/saved/cb_model.pkl` (chosen for production)
     - Cold-Start handler from `models/saved/cold_start.pkl`
     - Optionally load Collaborative Filtering model for future use
  
  2. **User Classification**:
     - Fetch user data from the course user API
     - Check if user exists in the training data (has rating/watch history)
     - If user has history: use Content-Based model
     - If user is new (no history): use Cold-Start handler
  
  3. **Recommendation Generation**:
     - **For known users**: Call `content_based_model.predict(user_id, top_k=20)` which:
       - Looks up user's genre preferences from training
       - Scores all movies by genre match (60%), popularity (25%), and recency (15%)
       - Returns top 20 movie IDs sorted by score
     
     - **For new users**: Call `cold_start_handler.predict_for_new_user(user_data, top_k=20)` which:
       - Parses user's "likes" and "dislikes" text from user API
       - Extracts mentioned movies and genres
       - Recommends popular movies from liked genres, avoiding disliked genres
       - Falls back to most popular movies if no preferences found
  
  4. **Response Format**: Convert the list of movie IDs to a comma-separated string and return as plain text (not JSON).
  
  5. **Error Handling**: If model prediction fails or user API is unavailable, return a fallback list of popular movies to ensure service availability.

### Pointers to implementation
- **Model training:** [`models/train_models.py`](models/train_models.py) - Script that trains both Collaborative Filtering and Content-Based models, plus the Cold-Start handler, and saves them to `models/saved/`.

- **Serving / ranking:** 
  - [`src/app.py`](src/app.py) - Flask API endpoint (currently placeholder, needs model integration)
  - [`models/content_based.py`](models/content_based.py) - Content-Based model with `predict()` method for ranking
  - [`models/cold_start.py`](models/cold_start.py) - Cold-Start handler with `predict_for_new_user()` method
  - [`models/collaborative_filtering.py`](models/collaborative_filtering.py) - Collaborative Filtering model (available but not used in production)

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
