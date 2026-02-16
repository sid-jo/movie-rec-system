#!/usr/bin/env python3
"""
Complete pipeline setup: Download Kafka logs from GCS to local for offline work
Downloads 3500 files so you can work entirely locally
"""
from google.cloud import storage
import os
import json

print("="*60)
print("SETTING UP LOCAL PIPELINE FOR OFFLINE WORK")
print("="*60)

# Create directory structure
print("\n1. Creating directory structure...")
os.makedirs('data/raw_logs', exist_ok=True)
os.makedirs('data/processed', exist_ok=True)
os.makedirs('models', exist_ok=True)
os.makedirs('notebooks', exist_ok=True)
print("✓ Directories created")

# Download Kafka logs from GCS
print("\n2. Downloading Kafka logs from GCS...")
print("   (This will take a few minutes for 3500 files)")

client = storage.Client(project='mlip-spring2026')
bucket = client.bucket('mlip-team2-movielog')

# Get 3500 files
blobs = list(bucket.list_blobs(prefix='raw_logs/', max_results=3500))
print(f"   Found {len(blobs)} files to download")

for i, blob in enumerate(blobs):
    filename = blob.name.split('/')[-1]
    local_path = f"data/raw_logs/{filename}"
    
    # Skip if already downloaded
    if os.path.exists(local_path):
        continue
    
    blob.download_to_filename(local_path)
    
    if (i + 1) % 100 == 0:
        print(f"   Downloaded {i + 1}/{len(blobs)} files...")

print(f"✓ Downloaded {len(blobs)} files to data/raw_logs/")

# Verify metadata exists locally
print("\n3. Verifying metadata files...")
if os.path.exists('metadata/users.json') and os.path.exists('metadata/movies.json'):
    with open('metadata/users.json') as f:
        users = json.load(f)
    with open('metadata/movies.json') as f:
        movies = json.load(f)
    print(f"✓ Users: {len(users)}")
    print(f"✓ Movies: {len(movies)}")
else:
    print("✗ Metadata not found. Run fetch_metadata.py first!")

# Create summary
print("\n" + "="*60)
print("LOCAL PIPELINE READY!")
print("="*60)
print("\nYou now have:")
print(f"  - {len(blobs)} Kafka log files in data/raw_logs/")
print(f"  - User metadata in metadata/users.json")
print(f"  - Movie metadata in metadata/movies.json")
print("\nNext steps:")
print("  1. Use notebooks/ for data exploration")
print("  2. Process data and save to data/processed/")
print("  3. Train models and save to models/")
print("  4. Everything works OFFLINE")
print("="*60)
