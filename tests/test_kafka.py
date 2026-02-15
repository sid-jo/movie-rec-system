# test_kafka.py
from kafka import KafkaConsumer

# Connect to Kafka through the tunnel
consumer = KafkaConsumer(
    'movielog2',  # Your team's topic
    bootstrap_servers=['localhost:9092'],
    auto_offset_reset='earliest',  # Start from beginning
    enable_auto_commit=True,
    group_id='team2-test'
)

print("Connected! Waiting for messages...")
for message in consumer:
    print(f"{message.value.decode('utf-8')}")
    break  # Just print first message to test