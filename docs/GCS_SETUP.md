# GCS Setup for VM

Connect to **gs://mlip-team2-movielog** (project: `mlip-spring2026`) from this VM.

## 1. Get credentials

### Option A: Service account key (recommended for VMs)

1. Go to [Google Cloud Console](https://console.cloud.google.com/storage/browser/mlip-team2-movielog?project=mlip-spring2026)
2. **IAM & Admin** → **Service Accounts** → create or select a service account
3. Create a **JSON key** and download it
4. Put the key file in a safe location (e.g. `~/.config/gcp/mlip-team2-sa.json`)
5. Restrict permissions: `chmod 600 ~/.config/gcp/mlip-team2-sa.json`

### Option B: gcloud Application Default Credentials

If you use `gcloud auth` with your own account:

```bash
gcloud auth application-default login
```

This uses your Google account; no key file needed.

## 2. Set environment variable

```bash
export GOOGLE_APPLICATION_CREDENTIALS="/path/to/your-key.json"
```

To make this persistent, add to `~/.bashrc`:

```bash
echo 'export GOOGLE_APPLICATION_CREDENTIALS="/path/to/your-key.json"' >> ~/.bashrc
source ~/.bashrc
```

## 3. Install dependencies

```bash
cd /home/schittam/projects/group-project-s26-model-impossible-1
source venv/bin/activate
pip install google-cloud-storage
```

## 4. Verify connection

```bash
python test/test_gcs.py
```

Or use the script:

```bash
python scripts/verify_gcs.py
```

## Usage in code

```python
from google.cloud import storage

client = storage.Client(project='mlip-spring2026')
bucket = client.bucket('mlip-team2-movielog')

# List blobs
for blob in bucket.list_blobs():
    print(blob.name)

# Upload
blob = bucket.blob('path/to/file.json')
blob.upload_from_filename('local_file.json')

# Download
blob = bucket.blob('path/to/file.json')
blob.download_to_filename('local_file.json')
```
