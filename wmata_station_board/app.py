from flask import Flask, render_template, request, jsonify
import json
import pandas as pd
import requests
import os
from functools import lru_cache

cwd = os.path.dirname(os.path.abspath(__file__))
app = Flask(__name__)

# Load config
def load_config():
    config = {}
    with open(cwd + "/config.txt") as f:
        for line in f:
            if '=' in line:
                key, val = line.strip().split("=", 1)
                config[key.strip()] = val.strip()
    return config

config = load_config()
API_KEY = config.get("API_KEY")
DEFAULT_STATION = config.get("DEFAULT_STATION", "Wiehle-Reston East")

# Load station layout and fallback patching data
station_df = pd.read_excel(cwd + "/Station_List.xlsx")
with open(cwd + "/backup_station.json") as _f:
    backup_data: dict = json.load(_f)

# Build list of stations for dropdown menu
station_names = station_df["DestinationName"].dropna().drop_duplicates().sort_values().tolist()

@lru_cache(maxsize=None)
def get_fallback(line_missing: bool, dest_missing: bool, loc: str, grp: str, line: str = ""):
    """Return fallback Line and DestinationName using backup_data if possible.

    When line is known, uses line-specific destination (e.g. SV vs OR at a shared station).
    When line is missing, picks the first line entry for that station/group.
    """
    station_entry = backup_data.get(loc, {})
    if not station_entry:
        return None, None

    fallback_line = None
    fallback_dest = None
    effective_line = line  # the line to use for destination lookup

    if line_missing:
        effective_line = next(iter(station_entry), None)
        fallback_line = effective_line

    if dest_missing:
        if effective_line and effective_line in station_entry:
            fallback_dest = station_entry[effective_line].get(grp)
        else:
            # Unknown line — use the first available entry for this group
            for groups in station_entry.values():
                fallback_dest = groups.get(grp)
                if fallback_dest:
                    break

    return fallback_line, fallback_dest

@lru_cache(maxsize=None)
def get_platform(location_code):
    """Get platform from station_df if available."""
    result = station_df[
        station_df["StationCode"].astype(str).str.strip().str.upper() == location_code
    ]
    if not result.empty and pd.notna(result.iloc[0]["Platform"]):
        return str(result.iloc[0]["Platform"]).strip()
    return None

@app.route("/")
def index():
    return render_template("index.html", stations=station_names, default_station=DEFAULT_STATION)

def _fix_wmata_encoding(s: str) -> str:
    """
    WMATA's Incidents API double-encodes smart quotes and similar characters:
    UTF-8 bytes are mis-decoded as cp1252, then re-encoded as UTF-8 in the JSON.
    Reverse the damage by encoding back to cp1252 bytes and decoding as UTF-8.
    """
    try:
        return s.encode("cp1252").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return s


def fetch_alerts() -> list:
    """Fetch current rail incidents from WMATA and return a simplified list."""
    try:
        resp = requests.get(
            "https://api.wmata.com/Incidents.svc/json/Incidents",
            headers={"api_key": API_KEY},
            timeout=8,
        )
        if resp.status_code != 200:
            return []
        incidents = json.loads(resp.content.decode("utf-8")).get("Incidents", [])
        return [
            {
                "description":    _fix_wmata_encoding(inc.get("Description", "")),
                "type":           inc.get("IncidentType", ""),
                "lines_affected": inc.get("LinesAffected", ""),
                "date_updated":   inc.get("DateUpdated", ""),
            }
            for inc in incidents
        ]
    except requests.RequestException:
        return []


@app.route("/get_predictions")
def get_predictions():
    selected_station = request.args.get("station")
    if not selected_station:
        return jsonify({})

    platform_rows = station_df[
        (station_df["DestinationName"] == selected_station) & (station_df["Platform"].notna())
    ]
    use_platforms = not platform_rows.empty

    headers = {"api_key": API_KEY}
    url = "https://api.wmata.com/StationPrediction.svc/json/GetPrediction/All"
    resp = requests.get(url, headers=headers)
    if resp.status_code != 200:
        return jsonify({"error": "Failed to fetch WMATA data"}), 500

    all_trains = resp.json().get("Trains", [])

    filtered = [
        t for t in all_trains
        if t.get("LocationName") == selected_station and t.get("DestinationName") != "No Passenger"
    ]

    for train in filtered:
        line_missing = train.get("Line") in [None, "", "No", "--"]
        dest_missing = train.get("DestinationName") in [None, "", "Train", "--"]

        if line_missing or dest_missing:
            loc = str(train.get("LocationCode", "")).strip().upper()
            grp = str(train.get("Group", "")).strip()
            known_line = "" if line_missing else str(train.get("Line", "")).strip()
            fallback_line, fallback_dest = get_fallback(line_missing, dest_missing, loc, grp, known_line)

            if fallback_line:
                train["Line"] = fallback_line
            if fallback_dest:
                train["DestinationName"] = fallback_dest

    grouped = {}

    if use_platforms:
        for train in filtered:
            location_code = str(train.get("LocationCode", "")).strip().upper()
            platform = get_platform(location_code)

            if not platform:
                continue

            line = train.get("Line", "UNK")
            group = str(train.get("Group", "0")).strip()
            canonical = backup_data.get(location_code, {}).get(line, {}).get(group, train["DestinationName"])
            label = f"{line} - {canonical}"

            if platform not in grouped:
                grouped[platform] = {}
            if line not in grouped[platform]:
                grouped[platform][line] = {}
            if group not in grouped[platform][line]:
                grouped[platform][line][group] = {}
            grouped[platform][line][group].setdefault(label, []).append({
                "Line": line,
                "Car": train["Car"],
                "Destination": train["DestinationName"],
                "Min": train["Min"]
            })
    else:
        for train in filtered:
            line = train.get("Line", "UNK")
            group = str(train.get("Group", "0")).strip()
            loc = str(train.get("LocationCode", "")).strip().upper()
            canonical = backup_data.get(loc, {}).get(line, {}).get(group, train["DestinationName"])
            label = f"{line} - {canonical}"

            if line not in grouped:
                grouped[line] = {}
            if group not in grouped[line]:
                grouped[line][group] = {}
            grouped[line][group].setdefault(label, []).append({
                "Line": line,
                "Car": train["Car"],
                "Destination": train["DestinationName"],
                "Min": train["Min"]
            })

    grouped["alerts"] = fetch_alerts()
    return jsonify(grouped)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)