"""
Cold-Start Handler for New Users
Uses user's self-described movie preferences (likes/dislikes) to make initial recommendations.
"""
import pandas as pd
import numpy as np
import ast
import re
import pickle
from collections import defaultdict


class ColdStartHandler:
    """
    Handles recommendations for users with no rating/watch history.
    
    How it works:
    1. Parse user's "likes" text to find movie titles they mention
    2. Extract genres from those movies
    3. Parse "dislikes" text to find genres to avoid
    4. Recommend popular movies from liked genres, avoiding disliked genres
    """
    
    def __init__(self):
        self.movie_features = {}  # movie_id -> {title, genres, popularity}
        self.genre_to_movies = defaultdict(list)  # genre -> list of movie_ids
        self.title_to_movie = {}  # lowercase title -> movie_id
        self.popular_movies = []  # Fallback: most popular movies overall
        
    def _parse_genres(self, genres_data):
        """Parse genre information from JSON format."""
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
    
    def _normalize_title(self, title):
        """
        Normalize movie title for matching.
        Remove special chars, lowercase, remove 'the/a/an' from start.
        """
        title = title.lower().strip()
        # Remove common prefixes
        for prefix in ['the ', 'a ', 'an ']:
            if title.startswith(prefix):
                title = title[len(prefix):]
        # Remove special characters except spaces
        title = re.sub(r'[^a-z0-9\s]', '', title)
        return title
    
    def _extract_movie_title_from_id(self, movie_id):
        """
        Extract readable title from movie_id.
        Example: 'toy+story+1995' -> 'toy story'
        """
        # Remove year (4 digits at end)
        parts = movie_id.split('+')
        title_parts = []
        
        for part in parts:
            if part.isdigit() and len(part) == 4:
                break
            title_parts.append(part)
        
        return ' '.join(title_parts)
        
    def fit(self, movies_metadata, watches_df=None):
        """
        Prepare the cold-start handler with movie database.
        
        Args:
            movies_metadata: Dict of movie_id -> movie data
            watches_df: Optional DataFrame to calculate popularity
        """
        print("Building movie index for cold-start recommendations...")
        
        # Calculate popularity if watches data provided
        popularity_scores = {}
        if watches_df is not None:
            movie_watch_counts = watches_df.groupby('movie_id').size()
            popularity_scores = movie_watch_counts.to_dict()
        
        # Index all movies
        for movie_id, movie_data in movies_metadata.items():
            genres = self._parse_genres(movie_data.get('genres', []))
            
            # Get title from movie data or parse from ID
            title = movie_data.get('title', self._extract_movie_title_from_id(movie_id))
            normalized_title = self._normalize_title(title)
            
            popularity = popularity_scores.get(movie_id, 0)
            
            # Store movie features
            self.movie_features[movie_id] = {
                'title': title,
                'genres': genres,
                'popularity': popularity
            }
            
            # Index by title for lookup
            self.title_to_movie[normalized_title] = movie_id
            
            # Index by genre
            for genre in genres:
                self.genre_to_movies[genre].append(movie_id)
        
        # Create fallback list: top 100 most popular movies
        sorted_by_popularity = sorted(
            self.movie_features.items(),
            key=lambda x: x[1]['popularity'],
            reverse=True
        )
        self.popular_movies = [movie_id for movie_id, _ in sorted_by_popularity[:100]]
        
        print(f"✓ Indexed {len(self.movie_features)} movies")
        print(f"✓ Found {len(self.genre_to_movies)} genres")
        print(f"✓ Built title index with {len(self.title_to_movie)} entries")
        
    def _find_mentioned_movies(self, text):
        """
        Extract movie titles mentioned in user's text.
        Uses simple string matching against known titles.
        """
        if not text or text is None or (isinstance(text, float) and np.isnan(text)):
            return []
        
        text_lower = text.lower()
        mentioned_movies = []
        
        # Try to match known movie titles in the text
        for normalized_title, movie_id in self.title_to_movie.items():
            if normalized_title in text_lower:
                mentioned_movies.append(movie_id)
        
        return mentioned_movies
    
    def _extract_genres_from_text(self, text, mentioned_movies):
        """
        Extract genres from movies mentioned in text.
        Also looks for direct genre mentions like "action movies" or "comedies".
        """
        genres = set()
        
        # Get genres from mentioned movies
        for movie_id in mentioned_movies:
            if movie_id in self.movie_features:
                genres.update(self.movie_features[movie_id]['genres'])
        
        # Also look for direct genre mentions in text
        if text and text is not None and not (isinstance(text, float) and np.isnan(text)):
            text_lower = text.lower()
            genre_keywords = {
                'action': 'Action',
                'comedy': 'Comedy',
                'comedies': 'Comedy',
                'drama': 'Drama',
                'horror': 'Horror',
                'thriller': 'Thriller',
                'romance': 'Romance',
                'romantic': 'Romance',
                'sci-fi': 'Science Fiction',
                'science fiction': 'Science Fiction',
                'fantasy': 'Fantasy',
                'animation': 'Animation',
                'animated': 'Animation',
                'documentary': 'Documentary',
                'crime': 'Crime',
                'mystery': 'Mystery',
                'adventure': 'Adventure'
            }
            
            for keyword, genre in genre_keywords.items():
                if keyword in text_lower:
                    genres.add(genre)
        
        return list(genres)
        
    def predict_for_new_user(self, user_data, top_k=20):
        """
        Generate recommendations for a new user based on their likes/dislikes.
        
        Args:
            user_data: Dict with user information (should have 'likes' and 'dislikes' fields)
            top_k: Number of recommendations to return
            
        Returns:
            List of movie_ids (as strings)
        """
        likes_text = user_data.get('likes', '')
        dislikes_text = user_data.get('dislikes', '')
        
        # Extract movies mentioned in likes
        liked_movies = self._find_mentioned_movies(likes_text)
        disliked_movies = self._find_mentioned_movies(dislikes_text)
        
        # Extract preferred and disliked genres
        liked_genres = self._extract_genres_from_text(likes_text, liked_movies)
        disliked_genres = self._extract_genres_from_text(dislikes_text, disliked_movies)
        
        print(f"Cold-start analysis:")
        print(f"  - Found {len(liked_movies)} liked movies -> {len(liked_genres)} genres: {liked_genres[:5]}")
        print(f"  - Found {len(disliked_movies)} disliked movies -> {len(disliked_genres)} disliked genres")
        
        # If we found liked genres, recommend from those
        if liked_genres:
            # Collect candidate movies from liked genres
            candidate_movies = set()
            for genre in liked_genres:
                if genre in self.genre_to_movies:
                    candidate_movies.update(self.genre_to_movies[genre])
            
            # Remove movies from disliked genres
            if disliked_genres:
                for genre in disliked_genres:
                    if genre in self.genre_to_movies:
                        candidate_movies -= set(self.genre_to_movies[genre])
            
            # Also remove explicitly disliked movies
            candidate_movies -= set(disliked_movies)
            
            # Score candidates by popularity
            movie_scores = {}
            for movie_id in candidate_movies:
                if movie_id in self.movie_features:
                    movie_scores[movie_id] = self.movie_features[movie_id]['popularity']
            
            # Return top_k most popular from liked genres
            sorted_movies = sorted(movie_scores.items(), key=lambda x: x[1], reverse=True)
            recommendations = [movie_id for movie_id, _ in sorted_movies[:top_k]]
            
            if recommendations:
                return recommendations
        
        # Fallback: return most popular movies overall
        print("  - Using fallback: popular movies")
        return self.popular_movies[:top_k]
    
    def save(self, filepath):
        """Save the cold-start handler to disk."""
        with open(filepath, 'wb') as f:
            pickle.dump(self, f)
        print(f"Cold-start handler saved to {filepath}")
    
    @staticmethod
    def load(filepath):
        """Load a cold-start handler from disk."""
        with open(filepath, 'rb') as f:
            return pickle.load(f)
