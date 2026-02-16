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
  We handle new users with no rating or watch history using their self-described preferences from signup. The approach works as follows:
  
  1. **Parse user preferences**: When a new user signs up, they may provide free-text descriptions in the `self_description_likes` and `self_description_dislikes` fields of their user profile (accessed via the user API).
  
  2. **Extract movie mentions**: The system searches the user's text for mentions of known movie titles by:
     - Normalizing movie titles (removing punctuation, converting to lowercase, replacing "+" with spaces)
     - Matching normalized titles against the movie catalog
     - Extracting up to 20 movie IDs mentioned in the likes text
  
  3. **Generate recommendations**:
     - **For users with preferences**: Returns movies explicitly mentioned in `self_description_likes` (up to 20), then fills remaining slots with popular movies that are NOT in the disliked list
     - **Fallback**: If no preferences are found or extraction fails, uses popularity-based recommendations with user-specific variation (hash-based offset for personalization)
  
  This approach leverages the user's self-described preferences to make personalized recommendations even before they have any viewing history. The production implementation prioritizes simplicity and speed, extracting mentioned movies directly rather than using genre inference.

- **Implementation:** 
  - **Production**: [`src/recommender.py`](src/recommender.py) - Function `get_recommendations()` implements cold-start using `_extract_movies_from_description()` which matches titles from `self_description_likes`/`self_description_dislikes` fields
  - **Training/Evaluation**: [`models/cold_start.py`](models/cold_start.py) - The `ColdStartHandler` class implements a more sophisticated cold-start logic with genre extraction (used during model development and evaluation)

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

- **Pointer to implementation:** [`models/train.py`](models/train.py) - This script loads processed data, trains both models sequentially, trains the cold-start handler, and saves all models to `models/artifacts/` directory as `.pkl` files. Training metadata (times, data stats) is saved to `models/artifacts/training_metadata.json`.

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



### Quality 2: Training cost
- **Metric:** Wall-clock time in seconds - the total elapsed time from start to completion of model training.

- **Data:** 
  - Time measurements captured during model training execution
  - Recorded separately for each model (Collaborative Filtering and Content-Based)
  - Stored in `models/artifacts/training_metadata.json` after training completes

- **Operationalization:** 
  1. Record system time using `time.time()` immediately before calling `model.fit()`
  2. Record system time immediately after `model.fit()` completes
  3. Compute difference: `training_time = end_time - start_time`
  4. Round to 2 decimal places and store in seconds
  5. Report training time for each model separately



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



### Quality 4: Model size (disk or memory)
- **Metric:** Disk space in megabytes - the size of the serialized model file stored on disk.

- **Data:** 
  - Serialized model files saved as pickle (.pkl) files
  - Collaborative Filtering model: `models/artifacts/cf_model.pkl`
  - Content-Based model: `models/artifacts/cb_model.pkl`

- **Operationalization:** 
  1. Use `os.path.getsize(model_path)` to get file size in bytes
  2. Convert bytes to megabytes: `size_mb = size_bytes / (1024 * 1024)`
  3. Round to 2 decimal places
  4. Report size in MB for each model file separately



### Comparison table

| Quality           | Collaborative Filtering | Content-Based |
|------------------|-------------------------|---------------|
| Prediction accuracy (NDCG@20) | 0.0568 | 0.0137 |
| Training cost (seconds) | 18.82 | 13.79 |
| Inference/throughput (avg ms) | 23.05 | 85.1 |
| Model size (MB) | 4307.14 | 3.97 |



### Choice for production
- **We use in production:** Collaborative Filtering Model (via NMF implementation)

- **Reason:** 
  Based on the evaluation results, we choose the Collaborative Filtering model for production, though it is implemented using Non-negative Matrix Factorization (NMF) in the actual serving code:
  
  1. **Accuracy**: The Collaborative Filtering model shows significantly better accuracy (NDCG@20: 0.0568 vs 0.0137), which is the primary quality metric for recommendation systems.
  
  2. **Inference latency**: At 23.05ms average latency, the CF model is well below the 600ms requirement, providing ample headroom for API overhead and network latency. The Content-Based model is slower (85.1ms), though still acceptable.
  
  3. **Model size trade-off**: While the CF model is much larger (4307.14 MB vs 3.97 MB), the accuracy improvement justifies the storage cost. The model is loaded once at startup and cached in memory.
  
  4. **Training efficiency**: CF trains in 18.82s vs 13.79s for Content-Based, a difference of only 5 seconds which is acceptable for periodic retraining.
  
  **Note**: The actual production API uses an NMF (Non-negative Matrix Factorization) implementation which provides similar collaborative filtering capabilities with efficient matrix operations. The evaluation was performed on the user-user similarity CF model, but the production system uses NMF for better scalability.

---

## 3. Prediction Service 

### Implementation
- **Stack:** Flask application running on port 8082, accessible at `http://0.0.0.0:8082` (or `http://<VM-address>:8082` for production).

- **Endpoint:** `GET /recommend/<userid>` → returns a single line with up to 20 comma-separated **movie IDs** (not titles, not JSON), ordered from highest to lowest recommendation score.

- **How ranking is derived:** 
  
  The API endpoint [`src/app.py`](src/app.py) implements a fully functional recommendation service using [`src/recommender.py`](src/recommender.py). The ranking logic follows a cascading fallback strategy:
  
  1. **Model Loading**: Models are lazy-loaded on first request from `models/artifacts/`:
     - NMF (Non-negative Matrix Factorization) model from `model_nmf.joblib` - for known users
     - Popularity model from `model_popularity.joblib` - for fallback recommendations
     - Cold-Start handler from `cold_start.joblib` - for new users
     - Valid movie IDs are loaded from `metadata/movies.json`
  
  2. **Recommendation Cascade** (in order of priority):
     
     **a) Cold-Start Path** (if user_data provided and contains preferences):
     - Extracts movie titles from `self_description_likes` and `self_description_dislikes` fields
     - Matches mentioned titles against the movie catalog using normalized title matching
     - Returns up to 20 movies from liked titles, then fills remaining slots with popular movies (excluding disliked movies)
     
     **b) NMF Model Path** (for known users in training data):
     - Uses Non-negative Matrix Factorization: `scores = W[user_idx] @ H` where W is user factors and H is movie factors
     - Selects top 30 candidates by score, filters to valid movie IDs, returns top 20
     - This provides collaborative filtering recommendations based on learned user-movie interactions
     
     **c) Popularity Fallback** (if NMF fails or user not found):
     - Uses deterministic hash-based selection from top popular movies
     - Hash of user_id determines starting offset in popularity list for personalization (10% requirement)
     - Returns 20 movies from the popularity-ranked list
     
     **d) Fixed Fallback** (last resort):
     - Returns a curated list of 10 highly-rated movies (e.g., "The Shawshank Redemption", "The Godfather", etc.)
     - Filtered to only include valid movie IDs from the catalog
  
  3. **Response Format**: The list of movie IDs is joined with commas and returned as plain text (not JSON), up to 20 movies.
  
  4. **Error Handling**: The cascading fallback ensures the service always returns recommendations even if models fail or user data is unavailable, maintaining service availability.

### Pointers to implementation
- **Model training:** [`models/train.py`](models/train.py) - Script that trains both Collaborative Filtering and Content-Based models, plus the Cold-Start handler, and saves them to `models/artifacts/` as `.pkl` files. Note: The production API uses NMF models trained separately and stored as `.joblib` files.

- **Serving / ranking:** 
  - [`src/app.py`](src/app.py) - Flask API endpoint that handles HTTP requests and calls the recommender
  - [`src/recommender.py`](src/recommender.py) - Core recommendation logic implementing the cascading fallback strategy (cold-start → NMF → popularity → fixed fallback)
  - [`models/cold_start.py`](models/cold_start.py) - Cold-Start handler implementation (used in training pipeline)
  - [`models/collaborative_filtering.py`](models/collaborative_filtering.py) - User-user similarity CF model (used for evaluation)
  - [`models/content_based.py`](models/content_based.py) - Content-Based model (used for evaluation)
  
- **Model artifacts:** Trained models are stored in `models/artifacts/`:
  - `model_nmf.joblib` - NMF model for production recommendations
  - `model_popularity.joblib` - Popularity-based fallback model
  - `cold_start.joblib` - Cold-start handler for new users
  - `evaluation_results.json` - Model comparison results
  - `training_metadata.json` - Training statistics and configuration

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
