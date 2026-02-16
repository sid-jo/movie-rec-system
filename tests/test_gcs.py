"""Test GCS connection to mlip-team2-movielog bucket."""
import os

from google.cloud import storage

PROJECT_ID = "mlip-spring2026"
BUCKET_NAME = "mlip-team2-movielog"

if not os.environ.get("GOOGLE_APPLICATION_CREDENTIALS"):
    print("WARNING: GOOGLE_APPLICATION_CREDENTIALS not set. Using gcloud ADC if available.")

client = storage.Client(project=PROJECT_ID)
bucket = client.bucket(BUCKET_NAME)

print("Testing GCS connection...")
try:
    buckets = list(client.list_buckets())
    print(f"Found {len(buckets)} bucket(s):")
    for b in buckets:
        print(f"  - {b.name}")
except Exception as e:
    print(f"(Skipping list_buckets - {e})")
    print("Attempting direct bucket access...")

blob = bucket.blob("test/hello.txt")
blob.upload_from_string("Hello from Team 2!")
print(f"\n✓ Successfully uploaded test file to gs://{BUCKET_NAME}/test/hello.txt")
