#!/usr/bin/env python3
"""Verify GCS connection to mlip-team2-movielog bucket."""

import os
import sys

PROJECT_ID = "mlip-spring2026"
BUCKET_NAME = "mlip-team2-movielog"


def main():
    creds = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
    if not creds:
        print("ERROR: GOOGLE_APPLICATION_CREDENTIALS is not set.")
        print("Set it to the path of your service account JSON key:")
        print('  export GOOGLE_APPLICATION_CREDENTIALS="/path/to/key.json"')
        sys.exit(1)
    if not os.path.isfile(creds):
        print(f"ERROR: Key file not found: {creds}")
        sys.exit(1)

    print("Testing GCS connection...")
    try:
        from google.cloud import storage

        client = storage.Client(project=PROJECT_ID)
        bucket = client.bucket(BUCKET_NAME)

        # List buckets (verify auth)
        buckets = list(client.list_buckets())
        print(f"✓ Authenticated. Found {len(buckets)} bucket(s) in project.")

        # Test bucket access
        blob = bucket.blob("test/verify_hello.txt")
        blob.upload_from_string("Hello from VM!")
        print(f"✓ Uploaded test file to gs://{BUCKET_NAME}/test/verify_hello.txt")

        # Clean up
        blob.delete()
        print("✓ Deleted test file.")
        print("\nGCS connection successful!")
    except Exception as e:
        print(f"ERROR: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
