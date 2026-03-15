"""Test GCS connection to mlip-team2-movielog bucket."""
import os
import pytest

# Skip this GCS integration test in CI where credentials are not available.
if os.getenv("CI", "").lower() == "true":
    pytest.skip("Skipping GCS-dependent test in CI environment.", allow_module_level=True)

import pytest

PROJECT_ID = "mlip-spring2026"
BUCKET_NAME = "mlip-team2-movielog"


@pytest.mark.integration
def test_gcs_can_upload_small_blob():
    if os.environ.get("RUN_INTEGRATION_TESTS") != "1":
        pytest.skip("integration test (set RUN_INTEGRATION_TESTS=1 to enable)")

    from google.cloud import storage

    client = storage.Client(project=PROJECT_ID)
    bucket = client.bucket(BUCKET_NAME)
    blob = bucket.blob("test/hello.txt")
    blob.upload_from_string("Hello from Team 2!")
    assert blob.exists()
