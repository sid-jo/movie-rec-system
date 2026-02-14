"""
Collaborative Filtering Recommendation Model
Uses user-user similarity based on rating patterns to recommend movies.
"""
import pandas as pd
import numpy as np
from sklearn.metrics.pairwise import cosine_similarity
import pickle


class CollaborativeFilteringModel:
    """
    User-based Collaborative Filtering recommender.
    
    How it works:
    1. Build a user-item rating matrix (users as rows, movies as columns)
    2. Compute similarity between users using cosine similarity
    3. For recommendations: find similar users who rated movies highly
    4. Recommend movies the target user hasn't seen yet
    """
    
    def __init__(self, min_common_items=5, top_similar_users=50):
        """
        Args:
            min_common_items: Minimum number of common rated items for similarity
            top_similar_users: Number of similar users to consider for recommendations
        """
        self.min_common_items = min_common_items
        self.top_similar_users = top_similar_users
        self.rating_matrix = None
        self.user_similarity = None
        self.user_ids = None
        self.movie_ids = None
        
    def fit(self, ratings_df):
        """
        Train the collaborative filtering model.
        
        Args:
            ratings_df: DataFrame with columns ['user_id', 'movie_id', 'rating']
        """
        print("Building user-item rating matrix...")
        # Create pivot table: rows=users, columns=movies, values=ratings
        self.rating_matrix = ratings_df.pivot_table(
            index='user_id',
            columns='movie_id',
            values='rating',
            fill_value=0  # Fill missing ratings with 0
        )
        
        # Convert user IDs to strings for consistent lookup
        self.rating_matrix.index = self.rating_matrix.index.astype(str)
        self.user_ids = self.rating_matrix.index.tolist()
        self.movie_ids = self.rating_matrix.columns.tolist()
        
        print(f"Matrix shape: {self.rating_matrix.shape[0]} users x {self.rating_matrix.shape[1]} movies")
        
        # Compute user-user similarity using cosine similarity
        print("Computing user similarity matrix (this may take a minute)...")
        # Convert to numpy array for faster computation
        rating_array = self.rating_matrix.values
        
        # Compute cosine similarity between all users
        self.user_similarity = cosine_similarity(rating_array)
        
        print(f"✓ Collaborative Filtering model trained successfully!")
        
    def predict(self, user_id, top_k=20):
        """
        Generate recommendations for a specific user.
        
        Args:
            user_id: The user to generate recommendations for
            top_k: Number of recommendations to return
            
        Returns:
            List of movie_ids (as strings)
        """
        # Convert user_id to string if necessary
        user_id = str(user_id) if not isinstance(user_id, str) else user_id
        
        # Check if user exists in our training data
        if user_id not in self.user_ids:
            return []  # No recommendations for unknown users
        
        # Get the index of this user in the similarity matrix
        user_idx = self.user_ids.index(user_id)
        
        # Get similarity scores for this user with all other users
        similarity_scores = self.user_similarity[user_idx]
        
        # Find the most similar users (excluding the user themselves)
        # Get indices of top similar users
        similar_user_indices = np.argsort(similarity_scores)[::-1][1:self.top_similar_users+1]
        
        # Get movies this user has already rated/watched
        user_rated_movies = set(
            self.rating_matrix.columns[self.rating_matrix.iloc[user_idx] > 0].tolist()
        )
        
        # Collect candidate movies from similar users
        movie_scores = {}
        
        for similar_user_idx in similar_user_indices:
            similarity_score = similarity_scores[similar_user_idx]
            
            # Skip if similarity is too low
            if similarity_score <= 0:
                continue
            
            # Get movies this similar user rated highly (7-10 stars on 1-10 scale)
            similar_user_ratings = self.rating_matrix.iloc[similar_user_idx]
            highly_rated = similar_user_ratings[similar_user_ratings >= 7.0]
            
            # Add these movies to candidates (weighted by similarity)
            for movie_id, rating in highly_rated.items():
                if movie_id not in user_rated_movies:
                    if movie_id not in movie_scores:
                        movie_scores[movie_id] = 0
                    # Weight the rating by user similarity
                    movie_scores[movie_id] += rating * similarity_score
        
        # Sort movies by score and return top_k
        if not movie_scores:
            return []
        
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
