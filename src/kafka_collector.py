#!/usr/bin/env python3
import json
import re
from datetime import datetime
from kafka import KafkaConsumer
import psycopg2
from psycopg2.extras import execute_values
import os

# Create data directory
os.makedirs('raw_data', exist_ok=True)

# Kafka consumer
consumer = KafkaConsumer(
    'movielog2',
    bootstrap_servers=['localhost:9092'],
    auto_offset_reset='earliest',  # Get all historical data
    enable_auto_commit=True,
    group_id='team2-collector',
    value_deserializer=lambda x: x.decode('utf-8')
)

# File for raw backup
current_date = datetime.now().strftime('%Y%m%d')
raw_file = open(f'raw_data/movielog_{current_date}.jsonl', 'a')

# Parse log entries
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
            # Extract recommended movies if status 200
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

print("Starting Kafka consumer... Press Ctrl+C to stop")
print(f"Saving raw data to: raw_data/movielog_{current_date}.jsonl")

message_count = 0
batch = []
BATCH_SIZE = 1000

try:
    for message in consumer:
        log_line = message.value
        
        # Save raw data
        raw_file.write(log_line + '\n')
        
        # Parse and collect
        parsed = parse_log_entry(log_line)
        if parsed:
            batch.append(parsed)
            
        message_count += 1
        
        # Print progress
        if message_count % 1000 == 0:
            print(f"Processed {message_count} messages...")
            raw_file.flush()  # Ensure data is written
            
        # Process batch (you can add DB insert here later)
        if len(batch) >= BATCH_SIZE:
            # TODO: Insert batch to database
            batch = []

except KeyboardInterrupt:
    print(f"\nStopping... Processed {message_count} total messages")
finally:
    raw_file.close()
    consumer.close()
