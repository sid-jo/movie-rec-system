"""
Content-Based Recommendation Model
Recommends movies based on user's genre preferences and movie features.
"""
import pandas as pd
import numpy as np
import ast
import pickle
from collections import defaultdict


class ContentBasedModel:
    """
    Content-based recommender using movie features (genres, popularity, recency).
    
    How it works:
    1. Build user profiles based on genres they rated highly
    2. Score all movies based on genre match with user profile
    3. Boost popular and recent movies
    4. Filter out movies already watched
    """
    
    def __init__(self):
        self.user_profiles = {}  # user_id -> genre preferences
        self.movie_features = {}  # movie_id -> {genres, popularity, year}
        self.all_genres = set()
        
    def _parse_genres(self, genres_data):
        """
        Parse genre information from JSON format.
        Handles format like: [{'id': 28, 'name': 'Action'}, {'id': 12, 'name': 'Adventure'}]
        """
        if genres_data is None or (isinstance(genres_data, float) and np.isnan(genres_data)):
            return []
        
        try:
            if isinstance(genres_data, str):
                parsed = ast.literal_eval(genres_data)
            else:
                parsed = genres_data
                
            if isinstance(parsed, list):
                return [g['name'] for g in parsed if isinstance(g, dict) and 'name' in g]
        except:
            pass
        
        return []
    
    def _extract_year(self, movie_id):
        """
        Extract release year from movie_id (usually ends with +YYYY).
        Example: 'toy+story+1995' -> 1995
        """
        try:
            parts = movie_id.split('+')
            for part in reversed(parts):
                if part.isdigit() and len(part) == 4:
                    year = int(part)
                    if 1900 <= year <= 2030:
                        return year
        except:
            pass
        return 2000  # Default year if can't parse
        
    def fit(self, ratings_df, movies_metadata, watches_df):
        """
        Train the content-based model.
        
        Args:
            ratings_df: DataFrame with ['user_id', 'movie_id', 'rating']
            movies_metadata: Dict of movie_id -> movie data (with 'genres' field)
            watches_df: DataFrame with ['user_id', 'movie_id', 'minutes_watched']
        """
        print("Building movie feature database...")
        
        # Calculate movie popularity (number of watches)
        movie_popularity = watches_df.groupby('movie_id')['minutes_watched'].agg(['count', 'sum'])
        
        # Build movie features
        for movie_id, movie_data in movies_metadata.items():
            genres = self._parse_genres(movie_data.get('genres', []))
            self.all_genres.update(genres)
            
            popularity = movie_popularity.loc[movie_id, 'count'] if movie_id in movie_popularity.index else 0
            year = self._extract_year(movie_id)
            
            self.movie_features[movie_id] = {
                'genres': set(genres),
                'popularity': popularity,
                'year': year,
                'age': 2026 - year  # Movie age (helpful for recency scoring)
            }
        
        print(f"Loaded {len(self.movie_features)} movies with features")
        print(f"Found {len(self.all_genres)} unique genres: {sorted(self.all_genres)[:10]}...")
        
        print("Building user preference profiles...")
        
        # Build user profiles based on highly-rated movies
        for user_id in ratings_df['user_id'].unique():
            user_ratings = ratings_df[ratings_df['user_id'] == user_id]
            
            # Count genres from highly-rated movies (rating >= 7 on 1-10 scale)
            genre_scores = defaultdict(float)
            total_high_ratings = 0
            
            for _, row in user_ratings.iterrows():
                movie_id = row['movie_id']
                rating = row['rating']
                
                # Only consider movies rated 7+ stars (70%+ on 1-10 scale)
                if rating >= 7.0 and movie_id in self.movie_features:
                    movie_genres = self.movie_features[movie_id]['genres']
                    for genre in movie_genres:
                        genre_scores[genre] += rating
                    total_high_ratings += 1
            
            # Normalize genre scores
            if total_high_ratings > 0:
                for genre in genre_scores:
                    genre_scores[genre] /= total_high_ratings
            
            self.user_profiles[str(user_id)] = {
                'genre_preferences': dict(genre_scores),
                'num_ratings': len(user_ratings),
                'avg_rating': user_ratings['rating'].mean()
            }
        
        print(f"✓ Content-Based model trained for {len(self.user_profiles)} users!")
        
    def predict(self, user_id, top_k=20):
        """
        Generate recommendations for a specific user.
        
        Args:
            user_id: The user to generate recommendations for
            top_k: Number of recommendations to return
            
        Returns:
            List of movie_ids (as strings)
        """
        user_id = str(user_id) if not isinstance(user_id, str) else user_id
        
        # Check if user exists
        if user_id not in self.user_profiles:
            return []  # No recommendations for unknown users
        
        user_profile = self.user_profiles[user_id]
        genre_prefs = user_profile['genre_preferences']
        
        if not genre_prefs:
            return []  # User has no clear preferences
        
        # Score all movies
        movie_scores = {}
        
        for movie_id, features in self.movie_features.items():
            # Calculate genre match score
            genre_score = 0.0
            for genre in features['genres']:
                if genre in genre_prefs:
                    genre_score += genre_prefs[genre]
            
            # Normalize by number of genres in movie
            if len(features['genres']) > 0:
                genre_score /= len(features['genres'])
            
            # Calculate recency score (prefer newer movies, but not too aggressively)
            # Movies from last 10 years get boost
            age = features['age']
            if age <= 10:
                recency_score = 1.0
            elif age <= 30:
                recency_score = 0.5
            else:
                recency_score = 0.2
            
            # Popularity score (normalize by max popularity)
            popularity_score = min(features['popularity'] / 100.0, 1.0)
            
            # Combined score: genre is most important, then popularity, then recency
            final_score = (
                genre_score * 0.6 +       # Genre match is most important
                popularity_score * 0.25 +  # Popular movies are safer bets
                recency_score * 0.15       # Slight preference for newer movies
            )
            
            movie_scores[movie_id] = final_score
        
        # Sort and return top_k
        sorted_movies = sorted(movie_scores.items(), key=lambda x: x[1], reverse=True)
        recommended_movies = [movie_id for movie_id, score in sorted_movies[:top_k]]
        
        return recommended_movies
    
    def save(self, filepath):
        """Save the trained model to disk."""
        with open(filepath, 'wb') as f:
            pickle.dump(self, f)
        print(f"Model saved to {filepath}")
    
    @staticmethod
    def load(filepath):
        """Load a trained model from disk."""
        with open(filepath, 'rb') as f:
            return pickle.load(f)
