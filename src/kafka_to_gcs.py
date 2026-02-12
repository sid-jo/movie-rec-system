#!/usr/bin/env python3
import json
import re
from datetime import datetime
from kafka import KafkaConsumer
from google.cloud import storage
from io import StringIO
import time

# GCS setup
storage_client = storage.Client()
BUCKET_NAME = 'mlip-team2-movielog'  # CHANGE THIS to your bucket name
bucket = storage_client.bucket(BUCKET_NAME)

BUFFER_SIZE = 10000   # Upload every 10k messages
BUFFER_TIME = 300     # Or every 5 minutes

# Kafka consumer
consumer = KafkaConsumer(
    'movielog2',
    bootstrap_servers=['localhost:9092'],
    auto_offset_reset='earliest',
    enable_auto_commit=True,
    group_id='team2-gcs-collector',
    value_deserializer=lambda x: x.decode('utf-8')
)

def parse_log_entry(log_line):
    """Parse different types of log entries"""
    parts = log_line.split(',', 2)
    if len(parts) < 3:
        return None
    
    timestamp = parts[0]
    userid = parts[1]
    action = parts[2]
    
    entry = {
        'timestamp': timestamp,
        'userid': userid,
        'raw': log_line
    }
    
    # Recommendation request
    if 'recommendation request' in action:
        match = re.search(r'status (\d+)', action)
        if match:
            entry['type'] = 'recommendation'
            entry['status'] = int(match.group(1))
            result_match = re.search(r'result: \[(.*?)\]', action)
            if result_match:
                entry['recommendations'] = result_match.group(1)
    
    # Movie watching
    elif '/data/m/' in action:
        match = re.search(r'/data/m/([^/]+)/(\d+)\.mpg', action)
        if match:
            entry['type'] = 'watch'
            entry['movieid'] = match.group(1)
            entry['minute'] = int(match.group(2))
    
    # Rating
    elif '/rate/' in action:
        match = re.search(r'/rate/(.+)=(\d+)', action)
        if match:
            entry['type'] = 'rating'
            entry['movieid'] = match.group(1)
            entry['rating'] = int(match.group(2))
    
    # New account
    elif 'create_account' in action:
        entry['type'] = 'signup'
    
    return entry

def upload_to_gcs(buffer, file_counter):
    """Upload buffer to GCS"""
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    gcs_path = f"raw_logs/{timestamp}_{file_counter}.jsonl"
    
    try:
        blob = bucket.blob(gcs_path)
        blob.upload_from_string(buffer.getvalue())
        print(f"✓ Uploaded to gs://{BUCKET_NAME}/{gcs_path} ({len(buffer.getvalue())} bytes)")
        return True
    except Exception as e:
        print(f"✗ GCS upload failed: {e}")
        # Save locally as backup
        import os
        os.makedirs('backup', exist_ok=True)
        with open(f'backup/{timestamp}_{file_counter}.jsonl', 'w') as f:
            f.write(buffer.getvalue())
        print(f"  Saved backup locally")
        return False

print("=" * 60)
print("Starting Kafka → GCS collector")
print(f"Target bucket: gs://{BUCKET_NAME}")
print("=" * 60)

message_count = 0
file_counter = 0
buffer = StringIO()
last_upload_time = time.time()

try:
    for message in consumer:
        log_line = message.value
        
        # Parse and write to buffer
        parsed = parse_log_entry(log_line)
        if parsed:
            buffer.write(json.dumps(parsed) + '\n')
        
        message_count += 1
        
        # Progress indicator
        if message_count % 1000 == 0:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] Buffered {message_count} messages...")
        
        # Upload when buffer is full or time elapsed
        current_time = time.time()
        if (message_count % BUFFER_SIZE == 0) or \
           (current_time - last_upload_time > BUFFER_TIME):
            
            if buffer.tell() > 0:  # If buffer has data
                upload_to_gcs(buffer, file_counter)
                file_counter += 1
                buffer = StringIO()  # Reset buffer
                last_upload_time = current_time

except KeyboardInterrupt:
    print(f"\n{'=' * 60}")
    print("Stopping... Uploading final buffer...")
    if buffer.tell() > 0:
        upload_to_gcs(buffer, file_counter)
    print(f"Total messages processed: {message_count}")
    print(f"Total files uploaded: {file_counter + 1}")
    print(f"{'=' * 60}")
    
finally:
    consumer.close()
