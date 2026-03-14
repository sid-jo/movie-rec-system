import os
import requests
import json
import pytest

# Skip this integration-style test when running in CI (requires GCS credentials).
if os.getenv("CI", "").lower() == "true":
    pytest.skip("Skipping GCS-dependent API format test in CI environment.", allow_module_level=True)

API_BASE = "http://128.2.220.241:8080"

# Test single user
print("Testing single user API...")
response = requests.get(f"{API_BASE}/user/1", timeout=10)
print(f"Status: {response.status_code}")
print(f"Response type: {type(response.json())}")
print(f"Response content:")
print(json.dumps(response.json(), indent=2)[:1000])

print("\n" + "="*60 + "\n")

# Test batch users
print("Testing batch user API (3 users)...")
response = requests.get(f"{API_BASE}/user/1,2,3", timeout=10)
print(f"Status: {response.status_code}")
print(f"Response type: {type(response.json())}")
print(f"Response content:")
print(json.dumps(response.json(), indent=2)[:1000])

print("\n" + "="*60 + "\n")

# Test single movie
print("Testing single movie API...")
# We need a real movie ID - let's get one from Kafka data
from google.cloud import storage
client = storage.Client(project='mlip-spring2026')
bucket = client.bucket('mlip-team2-movielog')
blobs = list(bucket.list_blobs(prefix='raw_logs/', max_results=1))

movieid = None
if blobs:
    content = blobs[0].download_as_string().decode('utf-8')
    for line in content.strip().split('\n')[:100]:
        if '"movieid"' in line:
            try:
                data = json.loads(line)
                movieid = data.get('movieid')
                if movieid:
                    break
            except:
                pass

if movieid:
    print(f"Using movie ID: {movieid}")
    response = requests.get(f"{API_BASE}/movie/{movieid}", timeout=10)
    print(f"Status: {response.status_code}")
    print(f"Response type: {type(response.json())}")
    print(f"Response content:")
    print(json.dumps(response.json(), indent=2)[:1000])
