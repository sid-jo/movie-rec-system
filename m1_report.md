# Milestone 1 Report: Movie Recommendations

## 1. Learning

**Data sources:**
- Kafka event stream: ratings (user-movie-rating), watch events (user-movie-minutes), signups.
- User/Movie API (`http://128.2.220.241:8080`): movie metadata (genres, title, license cost), user metadata including `self_description_likes` and `self_description_dislikes`.
- Processed data: `data/processed/ratings.csv`, `data/processed/watches.csv`; metadata: `metadata/movies.json`, `metadata/users.json`.

**Techniques:**
- **Model A (NMF – Collaborative Filtering):** Non-negative Matrix Factorization on the user-item rating matrix. Learns latent factors to predict ratings and rank movies for each user.
- **Model B (Popularity – Content-based):** Aggregates rating counts and mean ratings per movie; ranks by popularity. Uses genre metadata for optional content filtering.

**Why these choices:**
- NMF captures collaborative patterns (users with similar ratings get similar recommendations) and scales well with scikit-learn.
- Popularity provides a simple, robust baseline with no training cost and fast inference.

**Cold-start:**
We use the user API’s `self_description_likes` and `self_description_dislikes`. At inference:
1. Parse the text and match mentioned movie titles (normalized) against the catalog via a precomputed title→movie_id map.
2. Recommend matched liked movies first; avoid disliked movies.
3. Fill remaining slots with popular movies.

Implementation: [scripts/train.py](scripts/train.py) (builds `title_to_id`), [src/recommender.py](src/recommender.py) (`_extract_movies_from_description`, cold-start logic in `get_recommendations`).

**Training implementation:**
- [scripts/train.py](scripts/train.py) – trains both models and saves to `models/`.

---

## 2. Model Comparison

We define each quality with: (1) metric, (2) data, (3) operationalization.

| Quality | Metric | Data | Operationalization |
|--------|--------|------|---------------------|
| Prediction accuracy | RMSE between predicted and actual ratings | 80/20 train/validation split from `ratings.csv` | For NMF: predict ratings for held-out user-movie pairs and compute RMSE. For Popularity: use each movie’s mean training rating as predictor and compute RMSE. |
| Training cost | Wall-clock time (seconds) | Same machine, same data | Call `time.time()` before and after `model.fit()` (or aggregation). |
| Inference cost | Median latency (ms) and throughput (req/s) | 1000 recommendation requests | Call `get_recommendations(user_id)` 1000 times; measure each call with `time.perf_counter()`; report median latency and 1000/total_time as throughput. |
| Model size | Disk size (MB) | Serialized model files | `os.path.getsize(model_path) / (1024 * 1024)`. |

**Measurement implementation:** [scripts/compare_models.py](scripts/compare_models.py)

**Results:**

| Quality | NMF | Popularity |
|---------|-----|------------|
| Accuracy (RMSE) | ~6.1 | ~1.9 |
| Training (s) | ~3.6 | ~0 |
| Inference (median latency) | ~2.2 ms | ~1.8 ms |
| Size (MB) | ~7.3 | ~13.4 |

*Note: Run `python scripts/compare_models.py` to get current values.*

**Production choice:**
We use **NMF** as the primary model because it provides personalized recommendations for known users. Cold-start and popularity fallbacks handle new users. NMF’s inference latency (~2 ms) stays well under the 600 ms limit.

---

## 3. Prediction Service

**Implementation:**
- Flask app in [src/app.py](src/app.py).
- Endpoint: `GET /recommend/<userid>`.
- Response: single line, comma-separated list of up to 20 movie IDs (e.g. `movie1,movie2,...`).

**Flow:**
1. Fetch user metadata from the API (timeout 0.3 s).
2. Call `get_recommendations(userid, user_data)` in [src/recommender.py](src/recommender.py).
3. Return comma-separated movie IDs.

**Ranking:**
- Cold start: liked movies from self-descriptions first, then popular movies; exclude disliked.
- Known users: NMF scores (`W[user] @ H`) for all movies; top 20 by score.
- Fallback: popularity-ordered list, with offset by hashed `userid` for variety.

**Run:** `gunicorn -w 4 -b 0.0.0.0:8082 src.app:app`

**Links:** Training [scripts/train.py](scripts/train.py); Serving [src/app.py](src/app.py), [src/recommender.py](src/recommender.py).

---

## 4. Team Contract and Meeting Notes

**[Replace this section with your team’s answers. The report must address all five questions and include meeting notes with who / what / when.]**

1. **Communication expectations:**  
   [Channels used, expected response time, etc.]

2. **Project management:**  
   [How meetings are scheduled, notes taken, reminders sent; names of responsible members.]

3. **Work division:**  
   [Process for assigning tasks and responsibilities.]

4. **Handling delays/unresponsiveness:**  
   [What happens if someone is unresponsive or delayed.]

5. **Other agreements:**  
   [Anything else to avoid teamwork issues.]

**Meeting notes:**  
Include a screenshot or link to notes that show **who** was responsible for **what**, and by **when**, for this milestone.

See [docs/TEAM_CONTRACT.md](docs/TEAM_CONTRACT.md) for a template.

Example format:
| Who | What | When |
|-----|------|------|
| Alice | Train NMF model | Feb 10 |
| Bob   | Flask service   | Feb 11 |
| ...   | ...            | ...   |

---

*Report generated for Milestone 1. Update the Team Contract section with your actual team decisions and meeting notes before submission.*
