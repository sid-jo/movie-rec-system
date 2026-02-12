import json
import requests
import pandas as pd
from kafka import KafkaConsumer

# Configuration
KAFKA_SERVER = "128.2.220.241:9092"
API_BASE = "http://128.2.220.241:8080"
# Replace <TEAM_ID> with your actual team number (e.g., movielog12)
TOPIC_NAME = "movielog2" 

def fetch_metadata(endpoint, ids):
    """Fetch movie/user metadata in bulk (max 200)."""
    if not ids: return {}
    try:
        response = requests.get(f"{API_BASE}/{endpoint}/{','.join(map(str, ids))}", timeout=5)
        return {item['id'] if 'id' in item else item['user_id']: item for item in response.json()}
    except Exception as e:
        print(f"Metadata error: {e}")
        return {}

def start_collection(limit=5000):
    consumer = KafkaConsumer(
        TOPIC_NAME,
        bootstrap_servers=[KAFKA_SERVER],
        auto_offset_reset='earliest', # Start from the beginning of available logs
        value_deserializer=lambda x: x.decode('utf-8')
    )

    data = []
    print(f"Listening to {TOPIC_NAME}...")

    for message in consumer:
        line = message.value
        # Format: <time>,<userid>,GET /rate/<movieid>=<rating>
        if "GET /rate/" in line:
            parts = line.split(',')
            userid = parts[1]
            # Extract movieid and rating from 'GET /rate/movie+title=5'
            rating_part = parts[2].split('/')[-1].replace('rate/', '')
            movieid, rating = rating_part.split('=')
            
            data.append({
                'userid': userid,
                'movieid': movieid,
                'rating': int(rating)
            })

        if len(data) >= limit:
            break

    df = pd.DataFrame(data)
    df.to_csv("data/raw_ratings.csv", index=False)
    print(f"Saved {len(df)} ratings to data/raw_ratings.csv")

if __name__ == "__main__":
    start_collection()