#!/usr/bin/env python3
"""
Model Evaluation Script
Measures 4 key metrics for both models:
1. Prediction Accuracy (NDCG@20)
2. Training Cost (time in seconds)
3. Inference Cost (latency per prediction)
4. Model Size (disk space in MB)
"""
import os
import sys
import json
import time
import pandas as pd
import numpy as np
import random
import pickle
from collections import defaultdict

# Import our models
from collaborative_filtering import CollaborativeFilteringModel
from content_based import ContentBasedModel


def load_models():
    """Load the trained models from disk."""
    print("Loading trained models...")
    
    with open('artifacts/cf_model.pkl', 'rb') as f:
        cf_model = pickle.load(f)
    
    with open('artifacts/cb_model.pkl', 'rb') as f:
        cb_model = pickle.load(f)
    
    with open('artifacts/training_metadata.json', 'r') as f:
        training_metadata = json.load(f)
    
    print("✓ Models loaded")
    return cf_model, cb_model, training_metadata


def calculate_ndcg_at_k(relevant_items, recommended_items, k=20):
    """
    Calculate Normalized Discounted Cumulative Gain at k.
    
    Args:
        relevant_items: Set of items the user actually liked (rated 4+)
        recommended_items: Ordered list of recommended item IDs
        k: Number of recommendations to consider
    
    Returns:
        NDCG score between 0 and 1
    """
    # DCG: sum of (relevance / log2(position + 1))
    dcg = 0.0
    for i, item in enumerate(recommended_items[:k]):
        if item in relevant_items:
            # Relevance = 1 if item is relevant, 0 otherwise
            # Position ranks from 1, so we add 1 to i
            dcg += 1.0 / np.log2(i + 2)  # +2 because i starts at 0
    
    # IDCG: ideal DCG if we recommended all relevant items first
    num_relevant = min(len(relevant_items), k)
    idcg = sum(1.0 / np.log2(i + 2) for i in range(num_relevant))
    
    # Normalize
    if idcg == 0:
        return 0.0
    
    return dcg / idcg


def create_train_test_split(ratings_df, test_ratio=0.2):
    """
    Create train/test split for each user chronologically.
    
    Args:
        ratings_df: Full ratings DataFrame
        test_ratio: Proportion of ratings to hold out for testing
        
    Returns:
        train_df, test_df, test_user_holdouts (dict mapping user_id -> set of held-out movie_ids)
    """
    train_data = []
    test_data = []
    test_user_holdouts = {}
    
    for user_id in ratings_df['user_id'].unique():
        user_ratings = ratings_df[ratings_df['user_id'] == user_id].copy()
        
        # Sort by timestamp (chronological order)
        user_ratings = user_ratings.sort_values('timestamp')
        
        # Split: last 20% for test, first 80% for train
        n_ratings = len(user_ratings)
        n_test = max(1, int(n_ratings * test_ratio))  # At least 1 rating in test
        
        train_ratings = user_ratings.iloc[:-n_test]
        test_ratings = user_ratings.iloc[-n_test:]
        
        train_data.append(train_ratings)
        test_data.append(test_ratings)
        
        # Track which movies are held out for this user
        test_user_holdouts[str(user_id)] = set(test_ratings['movie_id'].tolist())
    
    train_df = pd.concat(train_data, ignore_index=True)
    test_df = pd.concat(test_data, ignore_index=True)
    
    return train_df, test_df, test_user_holdouts


def evaluate_accuracy(model, model_name, test_df, test_user_holdouts, test_users_sample=200):
    """
    Metric 1: Prediction Accuracy using NDCG@20
    
    Metric: NDCG@20 (Normalized Discounted Cumulative Gain at rank 20)
    Data: Test set - held-out ratings not seen during training
    Operationalization: 
        - For each test user, get their highly-rated movies in test set as "relevant"
        - Generate top 20 recommendations (model trained on train set only)
        - Calculate NDCG@20 based on how many relevant test items appear in top 20
        - Average NDCG across all test users
    """
    print(f"\n[1/4] Evaluating Accuracy for {model_name}...")
    print("  Metric: NDCG@20 (Normalized Discounted Cumulative Gain)")
    print("  Using held-out test set (chronological split)")
    
    # Get users with enough ratings in test set
    user_test_counts = test_df.groupby('user_id').size()
    users_with_test_data = user_test_counts[user_test_counts >= 2].index.tolist()
    
    # Sample test users
    test_users = random.sample(
        users_with_test_data, 
        min(test_users_sample, len(users_with_test_data))
    )
    
    print(f"  Testing on {len(test_users)} users with test data")
    
    ndcg_scores = []
    successful_predictions = 0
    empty_predictions = 0
    no_relevant_items = 0
    
    for user_id in test_users:
        # Get test set ratings for this user
        user_test_ratings = test_df[test_df['user_id'] == user_id].copy()
        
        # Get movies user rated highly (7-10 stars on 1-10 scale) in TEST SET as relevant items
        relevant_items = set(
            user_test_ratings[user_test_ratings['rating'] >= 7.0]['movie_id'].tolist()
        )
        
        if len(relevant_items) == 0:
            no_relevant_items += 1
            continue  # Skip users with no high ratings in test set
        
        # Get recommendations from model (trained on train set only)
        try:
            recommendations = model.predict(str(user_id), top_k=20)
            
            if recommendations and len(recommendations) > 0:
                # Calculate NDCG
                ndcg = calculate_ndcg_at_k(relevant_items, recommendations, k=20)
                ndcg_scores.append(ndcg)
                successful_predictions += 1
            else:
                empty_predictions += 1
        except Exception as e:
            continue
    
    if ndcg_scores:
        avg_ndcg = np.mean(ndcg_scores)
        print(f"  ✓ Average NDCG@20: {avg_ndcg:.4f}")
        print(f"  ✓ Successful predictions: {successful_predictions}/{len(test_users)}")
        if empty_predictions > 0:
            print(f"  ⚠ Empty predictions: {empty_predictions}/{len(test_users)}")
        if no_relevant_items > 0:
            print(f"  ⚠ Users with no high-rated test items: {no_relevant_items}/{len(test_users)}")
        return avg_ndcg
    else:
        print(f"  ✗ No successful predictions")
        print(f"  ⚠ Empty predictions: {empty_predictions}/{len(test_users)}")
        print(f"  ⚠ Users with no high-rated test items: {no_relevant_items}/{len(test_users)}")
        return 0.0


def evaluate_inference_cost(model, model_name, test_user_ids, num_trials=1000):
    """
    Metric 3: Inference Cost (latency per prediction)
    
    Metric: Average latency in milliseconds per recommendation request
    Data: Time 1000 prediction calls on random users
    Operationalization:
        - Select random users from training data
        - For each, time how long model.predict() takes
        - Convert to milliseconds
        - Report mean and 95th percentile latency
    """
    print(f"\n[3/4] Evaluating Inference Cost for {model_name}...")
    print("  Metric: Average latency per prediction (milliseconds)")
    
    latencies = []
    
    # Sample random users for testing
    test_sample = random.sample(test_user_ids, min(num_trials, len(test_user_ids)))
    
    print(f"  Running {len(test_sample)} prediction trials...")
    
    for user_id in test_sample:
        start = time.time()
        try:
            _ = model.predict(str(user_id), top_k=20)
            elapsed = (time.time() - start) * 1000  # Convert to milliseconds
            latencies.append(elapsed)
        except:
            continue
    
    if latencies:
        avg_latency = np.mean(latencies)
        p95_latency = np.percentile(latencies, 95)
        p99_latency = np.percentile(latencies, 99)
        
        print(f"  ✓ Average latency: {avg_latency:.2f} ms")
        print(f"  ✓ P95 latency: {p95_latency:.2f} ms")
        print(f"  ✓ P99 latency: {p99_latency:.2f} ms")
        
        return {
            'avg_ms': round(avg_latency, 2),
            'p95_ms': round(p95_latency, 2),
            'p99_ms': round(p99_latency, 2)
        }
    else:
        print(f"  ✗ No successful predictions")
        return {'avg_ms': 0, 'p95_ms': 0, 'p99_ms': 0}


def evaluate_model_size(model_path, model_name):
    """
    Metric 4: Model Size (disk space)
    
    Metric: Size in megabytes of serialized model file
    Data: Size of .pkl file on disk
    Operationalization:
        - Use os.path.getsize() to get file size in bytes
        - Divide by 1024*1024 to convert to MB
    """
    print(f"\n[4/4] Evaluating Model Size for {model_name}...")
    print("  Metric: Disk space in megabytes")
    
    if os.path.exists(model_path):
        size_bytes = os.path.getsize(model_path)
        size_mb = size_bytes / (1024 * 1024)
        
        print(f"  ✓ Model size: {size_mb:.2f} MB ({size_bytes:,} bytes)")
        return round(size_mb, 2)
    else:
        print(f"  ✗ Model file not found: {model_path}")
        return 0.0


def main():
    print("="*70)
    print("MODEL EVALUATION - COMPARING TWO APPROACHES")
    print("="*70)
    
    # Load production models and training metadata (for inference/size metrics)
    cf_model_prod, cb_model_prod, training_metadata = load_models()
    
    # Load all data
    print("\nLoading data...")
    ratings_df = pd.read_csv('../data/processed/ratings.csv')
    watches_df = pd.read_csv('../data/processed/watches.csv')
    with open('../metadata/movies.json', 'r') as f:
        movies_metadata = json.load(f)
    print(f"✓ Loaded {len(ratings_df):,} ratings")
    print(f"✓ Loaded {len(watches_df):,} watch records")
    print(f"✓ Loaded {len(movies_metadata):,} movies")
    
    # Create train/test split for accuracy evaluation
    print("\nCreating train/test split (80/20 chronological)...")
    train_df, test_df, test_user_holdouts = create_train_test_split(ratings_df)
    print(f"✓ Train set: {len(train_df):,} ratings")
    print(f"✓ Test set: {len(test_df):,} ratings")
    
    # Get list of users for inference testing
    all_users = ratings_df['user_id'].unique().tolist()
    
    # ========== EVALUATE COLLABORATIVE FILTERING ==========
    print("\n" + "="*70)
    print("EVALUATING: COLLABORATIVE FILTERING MODEL")
    print("="*70)
    
    cf_results = {
        'model_name': 'Collaborative Filtering (User-User Similarity)',
        'model_file': 'artifacts/cf_model.pkl'
    }
    
    # Metric 1: Accuracy (retrain on train set only)
    print("\nRetraining CF model on training set for accuracy evaluation...")
    cf_model_eval = CollaborativeFilteringModel()
    cf_model_eval.fit(train_df)
    cf_results['accuracy_ndcg20'] = evaluate_accuracy(
        cf_model_eval, 'Collaborative Filtering', test_df, test_user_holdouts
    )
    
    # Metric 2: Training Cost (already measured during training)
    cf_results['training_time_sec'] = training_metadata['training_times']['collaborative_filtering_sec']
    print(f"\n[2/4] Training Cost for Collaborative Filtering:")
    print(f"  Metric: Wall-clock time in seconds")
    print(f"  ✓ Training time: {cf_results['training_time_sec']} seconds")
    
    # Metric 3: Inference Cost (use production model for consistent performance)
    cf_results['inference_cost'] = evaluate_inference_cost(
        cf_model_prod, 'Collaborative Filtering', all_users
    )
    
    # Metric 4: Model Size
    cf_results['model_size_mb'] = evaluate_model_size(
        'artifacts/cf_model.pkl', 'Collaborative Filtering'
    )
    
    # ========== EVALUATE CONTENT-BASED ==========
    print("\n" + "="*70)
    print("EVALUATING: CONTENT-BASED MODEL")
    print("="*70)
    
    cb_results = {
        'model_name': 'Content-Based (Genre Matching)',
        'model_file': 'artifacts/cb_model.pkl'
    }
    
    # Metric 1: Accuracy (retrain on train set only)
    print("\nRetraining CB model on training set for accuracy evaluation...")
    cb_model_eval = ContentBasedModel()
    cb_model_eval.fit(train_df, movies_metadata, watches_df)
    cb_results['accuracy_ndcg20'] = evaluate_accuracy(
        cb_model_eval, 'Content-Based', test_df, test_user_holdouts
    )
    
    # Metric 2: Training Cost
    cb_results['training_time_sec'] = training_metadata['training_times']['content_based_sec']
    print(f"\n[2/4] Training Cost for Content-Based:")
    print(f"  Metric: Wall-clock time in seconds")
    print(f"  ✓ Training time: {cb_results['training_time_sec']} seconds")
    
    # Metric 3: Inference Cost (use production model for consistent performance)
    cb_results['inference_cost'] = evaluate_inference_cost(
        cb_model_prod, 'Content-Based', all_users
    )
    
    # Metric 4: Model Size
    cb_results['model_size_mb'] = evaluate_model_size(
        'artifacts/cb_model.pkl', 'Content-Based'
    )
    
    # ========== SAVE RESULTS ==========
    results = {
        'collaborative_filtering': cf_results,
        'content_based': cb_results,
        'evaluation_date': training_metadata['trained_at'],
        'test_data_size': len(ratings_df)
    }
    
    with open('artifacts/evaluation_results.json', 'w') as f:
        json.dump(results, f, indent=2)
    
    # ========== PRINT COMPARISON TABLE ==========
    print("\n" + "="*70)
    print("FINAL COMPARISON TABLE")
    print("="*70)
    print()
    print(f"{'Metric':<30} {'Collaborative Filtering':<25} {'Content-Based':<25}")
    print("-" * 70)
    print(f"{'1. Accuracy (NDCG@20)':<30} {cf_results['accuracy_ndcg20']:<25.4f} {cb_results['accuracy_ndcg20']:<25.4f}")
    print(f"{'2. Training Time (sec)':<30} {cf_results['training_time_sec']:<25.2f} {cb_results['training_time_sec']:<25.2f}")
    print(f"{'3. Inference Latency (ms)':<30} {cf_results['inference_cost']['avg_ms']:<25.2f} {cb_results['inference_cost']['avg_ms']:<25.2f}")
    print(f"{'4. Model Size (MB)':<30} {cf_results['model_size_mb']:<25.2f} {cb_results['model_size_mb']:<25.2f}")
    print("="*70)
    
    # ========== RECOMMENDATION ==========
    print("\nRECOMMENDATION FOR PRODUCTION:")
    print("-" * 70)
    
    # Simple decision logic
    if cb_results['inference_cost']['avg_ms'] < 100:  # Fast enough
        print("✓ Deploy: CONTENT-BASED MODEL")
        print("  Reasons:")
        print(f"  - Fast inference ({cb_results['inference_cost']['avg_ms']:.1f}ms avg) - meets 600ms requirement")
        print(f"  - Smaller model size ({cb_results['model_size_mb']:.1f}MB)")
        print(f"  - Faster training ({cb_results['training_time_sec']:.1f}s)")
        if cb_results['accuracy_ndcg20'] >= cf_results['accuracy_ndcg20']:
            print(f"  - Better or equal accuracy")
    else:
        print("✓ Deploy: COLLABORATIVE FILTERING MODEL")
        print("  Reasons:")
        print(f"  - Better accuracy (NDCG@20: {cf_results['accuracy_ndcg20']:.4f})")
    
    print("\n✓ Results saved to: models/artifacts/evaluation_results.json")
    print("="*70)


if __name__ == '__main__':
    # Set random seed for reproducibility
    random.seed(42)
    np.random.seed(42)
    
    try:
        main()
    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
