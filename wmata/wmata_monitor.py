"""
wmata_monitor.py

Runs two checks each time it is invoked:
  1. Incidents  – fetches current WMATA rail incidents (closures, delays, alerts)
                  and writes them to current_alerts.json for the station board.
  2. Station scan – fetches the current station list for every line and compares
                    against known_stations.json.  Any new or removed stations
                    are logged as warnings.  known_stations.json is updated so
                    the next run has the latest baseline.

Schedule this with cron or a systemd timer.  Example cron (every 10 minutes):
    */10 * * * * /usr/bin/python3 /home/jhumms/metro_board/wmata/wmata_monitor.py

On first run, known_stations.json is created from the live data (no false alarms).
"""

import json
import os
import requests
from datetime import datetime

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

def _load_config():
    config = {}
    path = os.path.join(SCRIPT_DIR, "config.txt")
    if os.path.exists(path):
        with open(path) as f:
            for line in f:
                line = line.strip()
                if "=" in line and not line.startswith("#"):
                    key, val = line.split("=", 1)
                    config[key.strip()] = val.strip()
    return config

_cfg = _load_config()
API_KEY = _cfg.get("WMATA_API_KEY", "")

KNOWN_STATIONS_FILE = os.path.join(SCRIPT_DIR, "known_stations.json")
ALERTS_FILE         = os.path.join(SCRIPT_DIR, "current_alerts.json")
LOG_FILE            = os.path.join(SCRIPT_DIR, "wmata_monitor.log")

# All WMATA rail line codes
LINE_CODES = ["RD", "BL", "OR", "SV", "GR", "YL"]

HEADERS = {"api_key": API_KEY}

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
def _log(message: str):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    entry = f"[{timestamp}] {message}"
    print(entry)
    with open(LOG_FILE, "a") as f:
        f.write(entry + "\n")

# ---------------------------------------------------------------------------
# Incidents / closures
# ---------------------------------------------------------------------------
def fetch_incidents() -> list:
    url = "https://api.wmata.com/Incidents.svc/json/Incidents"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=10)
    except requests.RequestException as exc:
        _log(f"ERROR fetching incidents: {exc}")
        return []

    if resp.status_code != 200:
        _log(f"ERROR fetching incidents: HTTP {resp.status_code}")
        return []

    return json.loads(resp.content.decode("utf-8")).get("Incidents", [])


def check_incidents():
    """Fetch incidents, log them, and persist to current_alerts.json."""
    incidents = fetch_incidents()
    alerts = []

    def _fix(s):
        try:
            return s.encode("cp1252").decode("utf-8")
        except (UnicodeEncodeError, UnicodeDecodeError):
            return s

    for inc in incidents:
        alert = {
            "description":   _fix(inc.get("Description", "")),
            "type":          inc.get("IncidentType", ""),
            "lines_affected": inc.get("LinesAffected", ""),
            "date_updated":  inc.get("DateUpdated", ""),
        }
        alerts.append(alert)
        _log(
            f"INCIDENT [{alert['type']}] "
            f"Lines: {alert['lines_affected'].strip(';')} | "
            f"{alert['description']}"
        )

    if not incidents:
        _log("No active incidents.")

    payload = {
        "alerts":     alerts,
        "updated_at": datetime.now().isoformat(),
    }
    with open(ALERTS_FILE, "w") as f:
        json.dump(payload, f, indent=2)

    return alerts

# ---------------------------------------------------------------------------
# Station-list scanning
# ---------------------------------------------------------------------------
def fetch_stations(line_code: str) -> dict:
    """Return {StationCode: StationName} for a given line."""
    url = f"https://api.wmata.com/Rail.svc/json/jStations?LineCode={line_code}"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=10)
    except requests.RequestException as exc:
        _log(f"ERROR fetching stations for {line_code}: {exc}")
        return {}

    if resp.status_code != 200:
        _log(f"ERROR fetching stations for {line_code}: HTTP {resp.status_code}")
        return {}

    stations = resp.json().get("Stations", [])
    return {s["Code"]: s["Name"] for s in stations}


def load_known_stations() -> dict:
    if not os.path.exists(KNOWN_STATIONS_FILE):
        return {}
    with open(KNOWN_STATIONS_FILE) as f:
        return json.load(f)


def save_known_stations(data: dict):
    with open(KNOWN_STATIONS_FILE, "w") as f:
        json.dump(data, f, indent=2)


def check_new_stations():
    """
    Compare live station lists against the saved baseline.
    Log any additions or removals, then update the baseline.
    On first run the baseline is created from live data (no false warnings).
    """
    known = load_known_stations()
    first_run = not known
    any_change = False

    for line_code in LINE_CODES:
        current = fetch_stations(line_code)
        if not current:
            continue  # API error already logged

        known_line = known.get(line_code, {})

        if first_run:
            # Seed the baseline silently
            known[line_code] = current
            continue

        new_codes     = set(current) - set(known_line)
        removed_codes = set(known_line) - set(current)

        for code in sorted(new_codes):
            _log(f"WARNING: NEW STATION on {line_code} line: {current[code]} ({code})")
            any_change = True

        for code in sorted(removed_codes):
            _log(f"WARNING: STATION REMOVED from {line_code} line: {known_line[code]} ({code})")
            any_change = True

        # Update baseline for this line
        known[line_code] = current

    if first_run:
        _log("First run – station baseline created from live data.")
    elif not any_change:
        _log("No station changes detected on any line.")

    save_known_stations(known)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    _log("=== WMATA Monitor run started ===")
    check_incidents()
    check_new_stations()
    _log("=== WMATA Monitor run complete ===")
