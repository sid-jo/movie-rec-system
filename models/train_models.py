#!/usr/bin/env python3
"""
Model Training Script
Trains both Collaborative Filtering and Content-Based models.
"""
import os
import sys
import json
import time
import pandas as pd
from datetime import datetime

# Import our models
from collaborative_filtering import CollaborativeFilteringModel
from content_based import ContentBasedModel
from cold_start import ColdStartHandler


def main():
    print("="*70)
    print("MOVIE RECOMMENDATION MODELS - TRAINING SCRIPT")
    print("="*70)
    
    # ========== STEP 1: Load Data ==========
    print("\n[1/5] Loading training data...")
    
    # Load processed data
    ratings_df = pd.read_csv('../data/processed/ratings.csv')
    watches_df = pd.read_csv('../data/processed/watches.csv')
    
    print(f"  ✓ Ratings: {len(ratings_df):,} records, {ratings_df['user_id'].nunique():,} users")
    print(f"  ✓ Watches: {len(watches_df):,} records")
    
    # Load metadata
    with open('../metadata/users.json', 'r') as f:
        users_metadata = json.load(f)
    
    with open('../metadata/movies.json', 'r') as f:
        movies_metadata = json.load(f)
    
    print(f"  ✓ Users metadata: {len(users_metadata):,} users")
    print(f"  ✓ Movies metadata: {len(movies_metadata):,} movies")
    
    # ========== STEP 2: Train Collaborative Filtering Model ==========
    print("\n[2/5] Training Collaborative Filtering Model...")
    print("  (This uses user-user similarity based on ratings)")
    
    cf_model = CollaborativeFilteringModel(
        min_common_items=5,
        top_similar_users=50
    )
    
    start_time = time.time()
    cf_model.fit(ratings_df)
    cf_training_time = time.time() - start_time
    
    print(f"  ✓ Training completed in {cf_training_time:.2f} seconds")
    
    # ========== STEP 3: Train Content-Based Model ==========
    print("\n[3/5] Training Content-Based Model...")
    print("  (This uses movie genre preferences)")
    
    cb_model = ContentBasedModel()
    
    start_time = time.time()
    cb_model.fit(ratings_df, movies_metadata, watches_df)
    cb_training_time = time.time() - start_time
    
    print(f"  ✓ Training completed in {cb_training_time:.2f} seconds")
    
    # ========== STEP 4: Train Cold-Start Handler ==========
    print("\n[4/5] Training Cold-Start Handler...")
    print("  (This handles new users with no history)")
    
    cold_start = ColdStartHandler()
    cold_start.fit(movies_metadata, watches_df)
    
    # ========== STEP 5: Save Models ==========
    print("\n[5/5] Saving trained models...")
    
    # Create saved models directory
    os.makedirs('saved', exist_ok=True)
    
    # Save models
    cf_model.save('saved/cf_model.pkl')
    cb_model.save('saved/cb_model.pkl')
    cold_start.save('saved/cold_start.pkl')
    
    # Save training metadata
    metadata = {
        'trained_at': datetime.now().isoformat(),
        'training_times': {
            'collaborative_filtering_sec': round(cf_training_time, 2),
            'content_based_sec': round(cb_training_time, 2)
        },
        'data_stats': {
            'num_ratings': len(ratings_df),
            'num_watches': len(watches_df),
            'num_users': ratings_df['user_id'].nunique(),
            'num_movies': len(movies_metadata),
            'ratings_per_user_avg': round(len(ratings_df) / ratings_df['user_id'].nunique(), 2),
            'watches_per_user_avg': round(len(watches_df) / watches_df['user_id'].nunique(), 2)
        },
        'model_configs': {
            'cf': {
                'min_common_items': cf_model.min_common_items,
                'top_similar_users': cf_model.top_similar_users
            }
        }
    }
    
    with open('saved/training_metadata.json', 'w') as f:
        json.dump(metadata, f, indent=2)
    
    print(f"\n  ✓ All models saved to models/saved/")
    
    # ========== Summary ==========
    print("\n" + "="*70)
    print("TRAINING SUMMARY")
    print("="*70)
    print(f"✓ Collaborative Filtering trained in {cf_training_time:.2f}s")
    print(f"✓ Content-Based trained in {cb_training_time:.2f}s")
    print(f"✓ Cold-Start handler ready")
    print(f"\nModels saved to:")
    print(f"  - models/saved/cf_model.pkl")
    print(f"  - models/saved/cb_model.pkl")
    print(f"  - models/saved/cold_start.pkl")
    print(f"  - models/saved/training_metadata.json")
    print("="*70)
    print("\nNext step: Run evaluation script")
    print("  python evaluate_models.py")
    print("="*70)


if __name__ == '__main__':
    try:
        main()
    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
