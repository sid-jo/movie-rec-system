#!/usr/bin/env python3
"""
Data preparation script - works entirely with local files
Processes Kafka logs into clean training data.
Run from project root: python notebooks/data_prep.py
"""
import json
import pandas as pd
from collections import defaultdict
import glob
import os

# Ensure we run from project root (parent of notebooks/)
_script_dir = os.path.dirname(os.path.abspath(__file__))
_project_root = os.path.dirname(_script_dir)
os.chdir(_project_root)

print("="*60)
print("DATA PREPARATION - WORKING LOCALLY")
print("="*60)

# 1. Load metadata
print("\n1. Loading metadata...")
with open('metadata/users.json') as f:
    users = json.load(f)
with open('metadata/movies.json') as f:
    movies = json.load(f)

print(f"   Users: {len(users):,}")
print(f"   Movies: {len(movies):,}")

# 2. Process local Kafka logs
print("\n2. Processing local Kafka log files...")
log_files = glob.glob('data/raw_logs/*.jsonl')
print(f"   Found {len(log_files)} log files")

ratings = []
watches = defaultdict(lambda: defaultdict(int))
recommendations = []
signups = []

for i, filepath in enumerate(log_files):
    with open(filepath) as f:
        for line in f:
            if not line.strip():
                continue
            try:
                data = json.loads(line)
                event_type = data.get('type')
                
                if event_type == 'rating':
                    ratings.append({
                        'user_id': data['userid'],
                        'movie_id': data['movieid'],
                        'rating': data['rating'],
                        'timestamp': data['timestamp']
                    })
                
                elif event_type == 'watch':
                    watches[data['userid']][data['movieid']] += 1
                
                elif event_type == 'recommendation':
                    recommendations.append({
                        'user_id': data['userid'],
                        'status': data.get('status'),
                        'timestamp': data['timestamp']
                    })
                
                elif event_type == 'signup':
                    signups.append({
                        'user_id': data['userid'],
                        'timestamp': data['timestamp']
                    })
                    
            except Exception as e:
                continue
    
    if (i + 1) % 500 == 0:
        print(f"   Processed {i + 1}/{len(log_files)} files...")

print(f"✓ Processing complete!")

# 3. Create DataFrames
print("\n3. Creating DataFrames...")

ratings_df = pd.DataFrame(ratings)
print(f"   Ratings: {len(ratings_df):,}")
print(f"   Unique users who rated: {ratings_df['user_id'].nunique():,}")
print(f"   Unique movies rated: {ratings_df['movie_id'].nunique():,}")

# Convert watches to DataFrame
watch_data = []
for user_id, movies_dict in watches.items():
    for movie_id, minutes in movies_dict.items():
        watch_data.append({
            'user_id': user_id,
            'movie_id': movie_id,
            'minutes_watched': minutes
        })

watches_df = pd.DataFrame(watch_data)
print(f"   Watch events: {len(watches_df):,}")
print(f"   Unique users who watched: {watches_df['user_id'].nunique():,}")

# 4. Save processed data
print("\n4. Saving processed data...")
os.makedirs('data/processed', exist_ok=True)

ratings_df.to_csv('data/processed/ratings.csv', index=False)
watches_df.to_csv('data/processed/watches.csv', index=False)
pd.DataFrame(recommendations).to_csv('data/processed/recommendations.csv', index=False)
pd.DataFrame(signups).to_csv('data/processed/signups.csv', index=False)

print("✓ Saved to data/processed/")
print("   - ratings.csv")
print("   - watches.csv")
print("   - recommendations.csv")
print("   - signups.csv")

# 5. Data summary
print("\n" + "="*60)
print("DATA SUMMARY")
print("="*60)
print(f"Total ratings: {len(ratings_df):,}")
print(f"Total watch events: {len(watches_df):,}")
print(f"Unique users: {ratings_df['user_id'].nunique():,}")
print(f"Unique movies: {ratings_df['movie_id'].nunique():,}")
print(f"\nRating distribution:")
print(ratings_df['rating'].value_counts().sort_index())
print("="*60)
print("\nData preparation complete!")
print("   You can now train models using data/processed/*.csv")
print("="*60)
