#!/usr/bin/env python3
import json
from datetime import datetime
from kafka import KafkaConsumer
import psycopg2
from psycopg2.extras import execute_values
import os
from src.kafka_parsing import parse_log_entry

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
