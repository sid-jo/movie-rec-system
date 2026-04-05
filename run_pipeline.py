#!/usr/bin/env python3
"""
Complete Pipeline Runner for Milestone 1
Orchestrates training, evaluation, and deployment.
"""
import os
import sys

print("="*70)
print("MILESTONE 1: MOVIE RECOMMENDATION PIPELINE")
print("="*70)

# Check if we're in the right directory
if not os.path.exists('models'):
    print("\n❌ ERROR: Must run from project root directory")
    print("   Current directory:", os.getcwd())
    print("   Expected directory structure:")
    print("     - models/")
    print("     - data/processed/")
    print("     - metadata/")
    sys.exit(1)

# Step 1: Check data availability
print("\n[Step 1] Checking data availability...")
required_files = [
    'data/processed/ratings.csv',
    'data/processed/watches.csv',
    'metadata/users.json',
    'metadata/movies.json'
]

missing_files = [f for f in required_files if not os.path.exists(f)]
if missing_files:
    print("❌ Missing required data files:")
    for f in missing_files:
        print(f"   - {f}")
    print("\nPlease run data preparation first:")
    print("   python notebooks/data_prep.py")
    sys.exit(1)

print("✓ All required data files present")

# Step 2: Train models
print("\n[Step 2] Training models...")
print("-" * 70)
os.chdir('models')
exit_code = os.system('python train_models.py')
os.chdir('..')

if exit_code != 0:
    print("\n❌ Model training failed!")
    sys.exit(1)

# Step 3: Evaluate models
print("\n[Step 3] Evaluating and comparing models...")
print("-" * 70)
os.chdir('models')
exit_code = os.system('python evaluate_models.py')
os.chdir('..')

if exit_code != 0:
    print("\n❌ Model evaluation failed!")
    sys.exit(1)

# Step 4: Summary
print("\n" + "="*70)
print("PIPELINE COMPLETE!")
print("="*70)
print("\nGenerated artifacts:")
print("  ✓ models/saved/cf_model.pkl")
print("  ✓ models/saved/cb_model.pkl")
print("  ✓ models/saved/cold_start.pkl")
print("  ✓ models/saved/training_metadata.json")
print("  ✓ models/saved/evaluation_results.json")

print("\nNext steps:")
print("  1. Review evaluation results:")
print("     cat models/saved/evaluation_results.json")
print("\n  2. Start the recommendation API:")
print("     python src/app.py")
print("\n  3. Test the API locally:")
print("     curl http://localhost:8082/recommend/123")

print("\n" + "="*70)
print("Ready for Milestone 1 submission!")
print("="*70)
