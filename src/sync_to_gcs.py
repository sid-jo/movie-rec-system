import os
import glob
from google.cloud import storage

# --- CONFIGURATION ---
LOCAL_LOGS_DIR = '../raw_logs/'
BUCKET_NAME = 'mlip-team2-movielog'
GCS_PREFIX = 'raw_logs/' # Folder inside your bucket

def sync_and_purge():
    # Initialize GCS client
    client = storage.Client()
    bucket = client.bucket(BUCKET_NAME)
    
    # Find all .jsonl files
    files = glob.glob(os.path.join(LOCAL_LOGS_DIR, "*.jsonl"))
    
    if not files:
        print("No log files found to sync.")
        return

    print(f"Found {len(files)} files. Starting upload...")

    for local_file in files:
        file_name = os.path.basename(local_file)
        blob = bucket.blob(os.path.join(GCS_PREFIX, file_name))
        
        try:
            # 1. Upload the file
            print(f"Uploading {file_name}...", end="\r")
            blob.upload_from_filename(local_file)
            
            # 2. Verify and Delete
            if blob.exists():
                os.remove(local_file)
                print(f"✓ Synced and Deleted: {file_name}")
            else:
                print(f"X Upload failed for {file_name}, keeping local copy.")
                
        except Exception as e:
            print(f"Error processing {file_name}: {e}")

if __name__ == "__main__":
    sync_and_purge()