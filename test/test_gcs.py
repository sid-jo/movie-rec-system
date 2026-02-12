from google.cloud import storage

# Initialize client
client = storage.Client()

# List buckets to test connection
print("Testing GCS connection...")
buckets = list(client.list_buckets())
print(f"Found {len(buckets)} bucket(s):")
for bucket in buckets:
    print(f"  - {bucket.name}")

# Test upload
bucket_name = "mlip-team2-movielog-ryanw3"  # Change to your bucket name
bucket = client.bucket(bucket_name)
blob = bucket.blob("test/hello.txt")
blob.upload_from_string("Hello from Team 2!")
print(f"\n✓ Successfully uploaded test file to gs://{bucket_name}/test/hello.txt")
