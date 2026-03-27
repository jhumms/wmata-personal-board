"""
generate_backup.py

Builds backup_station.json from the live WMATA API.
Maps each (StationCode, Line, Group) → DestinationName (the terminal station
for that direction).  app.py uses this as a fallback when the real-time
predictions API returns missing or placeholder Line/DestinationName fields.

Run this once to generate the file, then re-run whenever station names change
(wmata_monitor.py will log warnings when that happens).

Output: ../wmata_station_board/backup_station.json
"""

import json
import os
import requests

SCRIPT_DIR  = os.path.dirname(os.path.abspath(__file__))
OUTPUT_FILE = os.path.join(SCRIPT_DIR, "..", "wmata_station_board", "backup_station.json")

BASE = "https://api.wmata.com/Rail.svc/json"


def _load_api_key() -> str:
    candidates = [
        os.path.join(SCRIPT_DIR, "config.txt"),
        os.path.join(SCRIPT_DIR, "..", "wmata_station_board", "config.txt"),
    ]
    for config_path in candidates:
        if not os.path.exists(config_path):
            continue
        with open(config_path) as f:
            for line in f:
                line = line.strip()
                if "=" in line and not line.startswith("#"):
                    key, val = line.split("=", 1)
                    if key.strip() in ("WMATA_API_KEY", "API_KEY"):
                        return val.strip()
    raise RuntimeError("API key not found in wmata/config.txt or wmata_station_board/config.txt")


def _get(url: str, headers: dict) -> dict:
    resp = requests.get(url, headers=headers, timeout=10)
    resp.raise_for_status()
    return resp.json()


def fetch_lines(headers: dict) -> list[dict]:
    return _get(f"{BASE}/jLines", headers)["Lines"]


def fetch_station_name(code: str, headers: dict) -> str:
    data = _get(f"{BASE}/jStationInfo?StationCode={code}", headers)
    return data["Name"]


def fetch_stations_for_line(line_code: str, headers: dict) -> list[str]:
    """Return list of station codes for a line (unordered)."""
    data = _get(f"{BASE}/jStations?LineCode={line_code}", headers)
    return [s["Code"] for s in data.get("Stations", [])]


# jLines StartStationCode is stale for Silver Line (pre-Phase-2 value N06).
# Override any lines where the API hasn't been updated.
TERMINAL_OVERRIDES: dict[str, tuple[str, str]] = {
    "SV": ("N12", "G05"),   # Ashburn → Downtown Largo (jLines still shows N06)
}


def build_backup(headers: dict) -> dict:
    """
    Returns a nested dict:
      { StationCode: { LineCode: { "1": DestName, "2": DestName } } }

    Convention (matches existing backup_station.xlsx):
      Group "1" → trains heading toward the jLines EndStation
      Group "2" → trains heading toward the jLines StartStation
    """
    lines = fetch_lines(headers)
    backup: dict = {}

    for line in lines:
        code  = line["LineCode"]
        start = line["StartStationCode"]
        end   = line["EndStationCode"]

        if code in TERMINAL_OVERRIDES:
            start, end = TERMINAL_OVERRIDES[code]

        start_name = fetch_station_name(start, headers)
        end_name   = fetch_station_name(end, headers)

        station_codes = fetch_stations_for_line(code, headers)

        print(f"  {code}: {start_name} (Group 2) ↔ {end_name} (Group 1)  [{len(station_codes)} stations]")

        for sc in station_codes:
            if sc == start:
                # Start terminal — all trains depart toward the end
                g1_dest = end_name
                g2_dest = end_name
            elif sc == end:
                # End terminal — all trains depart toward the start
                g1_dest = end_name    # placeholder; Group 1 trains don't depart from here
                g2_dest = start_name
            else:
                g1_dest = end_name
                g2_dest = start_name

            backup.setdefault(sc, {})[code] = {"1": g1_dest, "2": g2_dest}

        for dest_key in ("InternalDestination1", "InternalDestination2"):
            internal_code = line.get(dest_key, "")
            if not internal_code:
                continue
            internal_name = fetch_station_name(internal_code, headers)
            print(f"    {code} internal terminal: {internal_name} ({internal_code})")

    return backup


def main():
    api_key = _load_api_key()
    headers = {"api_key": api_key}

    print("Fetching WMATA line data...")
    backup = build_backup(headers)

    out_path = os.path.normpath(OUTPUT_FILE)
    with open(out_path, "w") as f:
        json.dump(backup, f, indent=2)

    total = sum(len(lines) * 2 for lines in backup.values())
    print(f"\nWrote {len(backup)} stations / {total} (station, line, group) entries → {out_path}")


if __name__ == "__main__":
    main()
