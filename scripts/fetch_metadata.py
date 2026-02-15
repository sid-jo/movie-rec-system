#!/usr/bin/env python3
import requests
import json
import time
from google.cloud import storage
import os

API_BASE = "http://128.2.220.241:8080"
BATCH_SIZE = 200  # API accepts up to 200 IDs per request

# First, extract unique IDs from GCS
print("Step 1: Extracting unique user and movie IDs from Kafka data...")
client = storage.Client(project='mlip-spring2026')
bucket = client.bucket('mlip-team2-movielog')
blobs = list(bucket.list_blobs(prefix='raw_logs/'))

userids = set()
movieids = set()

for i, blob in enumerate(blobs):
    print(f"  Processing file {i+1}/{len(blobs)}: {blob.name}")
    content = blob.download_as_string().decode('utf-8')
    for line in content.strip().split('\n'):
        if not line:
            continue
        try:
            data = json.loads(line)
            if 'userid' in data:
                userids.add(data['userid'])
            if 'movieid' in data:
                movieids.add(data['movieid'])
        except:
            continue

print(f"\n✓ Found {len(userids)} unique users, {len(movieids)} unique movies")

# Fetch metadata in batches
def fetch_batch(endpoint, ids, batch_size=200):
    """Fetch metadata in batches - API returns a list"""
    all_data = {}
    id_list = sorted(list(ids))
    
    for i in range(0, len(id_list), batch_size):
        batch = id_list[i:i+batch_size]
        batch_str = ','.join(str(x) for x in batch)
        
        try:
            response = requests.get(f"{API_BASE}/{endpoint}/{batch_str}", timeout=30)
            if response.status_code == 200:
                batch_data = response.json()
                
                # API returns a list, convert to dict with ID as key
                if isinstance(batch_data, list):
                    for item in batch_data:
                        # For users, key is 'user_id'; for movies, key is 'id'
                        if endpoint == 'user':
                            item_id = item.get('user_id')
                        else:
                            item_id = item.get('id')
                        
                        if item_id:
                            all_data[str(item_id)] = item
                    
                    print(f"  ✓ Fetched {len(batch_data)} {endpoint}s (batch {i//batch_size + 1}/{(len(id_list)-1)//batch_size + 1})")
                else:
                    print(f"  ⚠ Unexpected response format for batch {i//batch_size + 1}")
            else:
                print(f"  ✗ Error {response.status_code} for batch {i//batch_size + 1}")
            
            time.sleep(0.5)  # Rate limiting - be nice to the API
        except Exception as e:
            print(f"  ✗ Error fetching batch: {e}")
    
    return all_data

print("\nStep 2: Fetching user metadata...")
user_data = fetch_batch('user', userids)

print("\nStep 3: Fetching movie metadata...")
movie_data = fetch_batch('movie', movieids)

# Save to GCS
print("\nStep 4: Saving metadata to GCS...")
user_blob = bucket.blob('metadata/users.json')
user_blob.upload_from_string(json.dumps(user_data, indent=2))
print(f"✓ Saved {len(user_data)} users to gs://mlip-team2-movielog/metadata/users.json")

movie_blob = bucket.blob('metadata/movies.json')
movie_blob.upload_from_string(json.dumps(movie_data, indent=2))
print(f"✓ Saved {len(movie_data)} movies to gs://mlip-team2-movielog/metadata/movies.json")

# Also save locally
os.makedirs('metadata', exist_ok=True)
with open('metadata/users.json', 'w') as f:
    json.dump(user_data, f, indent=2)
with open('metadata/movies.json', 'w') as f:
    json.dump(movie_data, f, indent=2)

print("\n" + "="*60)
print("Done! Metadata fetched and saved.")
print(f"Users: {len(user_data)}")
print(f"Movies: {len(movie_data)}")

# Show sample with self-descriptions
users_with_likes = [u for u in user_data.values() if u.get('self_description_likes')]
print(f"Users with likes: {len(users_with_likes)}")
print(f"Users with dislikes: {len([u for u in user_data.values() if u.get('self_description_dislikes')])}")

if users_with_likes:
    print("\nSample user with preferences:")
    sample = users_with_likes[0]
    print(f"  User {sample['user_id']}: {sample['occupation']}, {sample['gender']}, age {sample['age']}")
    print(f"  Likes: {sample['self_description_likes'][:100]}...")
print("="*60)