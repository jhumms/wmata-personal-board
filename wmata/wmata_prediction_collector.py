import requests
import pandas as pd
import os
from datetime import datetime

# --- CONFIGURATION ---
# Copy config.example.txt to config.txt and set your API key there.
def _load_config():
    config = {}
    config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.txt")
    if os.path.exists(config_path):
        with open(config_path) as f:
            for line in f:
                line = line.strip()
                if "=" in line and not line.startswith("#"):
                    key, val = line.split("=", 1)
                    config[key.strip()] = val.strip()
    return config

_cfg = _load_config()
API_KEY = _cfg.get("WMATA_API_KEY", os.environ.get("WMATA_API_KEY", ""))
OUTPUT_CSV = "/home/jhumms/wmata/rail_predictions.csv"
WMATA_API_URL = "https://api.wmata.com/StationPrediction.svc/json/GetPrediction/All"

# --- Ensure Output Directory Exists ---
os.makedirs(os.path.dirname(OUTPUT_CSV), exist_ok=True)

def fetch_predictions():
    headers = {"api_key": API_KEY}
    response = requests.get(WMATA_API_URL, headers=headers)
    if response.status_code == 200:
        data = response.json().get("Trains", [])
        timestamp = datetime.now().isoformat()
        for train in data:
            train["CollectedAt"] = timestamp
        return data
    else:
        print(f"Failed to fetch WMATA data: {response.status_code}")
        return []

def save_unique_predictions(new_data):
    if not new_data:
        return

    new_df = pd.DataFrame(new_data)
    expected_columns = [
        "Car", "Destination", "DestinationCode", "DestinationName",
        "Group", "Line", "LocationCode", "LocationName", "Min", "CollectedAt"
    ]
    new_df = new_df.reindex(columns=expected_columns)

    if os.path.exists(OUTPUT_CSV):
        existing_df = pd.read_csv(OUTPUT_CSV)
        combined_df = pd.concat([existing_df, new_df], ignore_index=True)
    else:
        combined_df = new_df

    # Drop duplicates based on all columns except CollectedAt
    deduped_df = combined_df.drop_duplicates(subset=[
        "Car", "Destination", "DestinationCode", "DestinationName",
        "Group", "Line", "LocationCode", "LocationName", "Min"
    ])

    # Save back to CSV
    deduped_df.to_csv(OUTPUT_CSV, index=False)

if __name__ == "__main__":
    predictions = fetch_predictions()
    save_unique_predictions(predictions)
