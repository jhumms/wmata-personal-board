# Metro Board

A Raspberry Pi–hosted web dashboard that displays real-time DC Metro (WMATA) train arrivals and system alerts, styled as a classic split-flap departure board.

![Terminal-style gold-on-black departure board](https://img.shields.io/badge/display-gold%20on%20black-FFD700?style=flat)

---

## Features

- Real-time train arrival predictions for any WMATA rail station
- Live service alerts and station closure warnings displayed as a blinking banner
- Flip-card animation when arrival minutes change
- Blinking highlight for trains arriving now
- Platform-aware layout for multi-platform stations (e.g. Fort Totten)
- Automatic 30-second refresh
- Companion monitor script that detects new or removed stations per line and logs all active incidents

---

## Project Structure

```
metro_board/
├── wmata_station_board/        # Flask web application
│   ├── app.py                  # Main Flask app + WMATA API calls
│   ├── config.txt              # Your API key and default station (gitignored)
│   ├── config.example.txt      # Template — copy to config.txt to get started
│   ├── Station_List.xlsx       # Station codes, names, and platform assignments
│   ├── backup_station.xlsx     # Fallback line/destination mappings
│   ├── templates/
│   │   └── index.html          # Departure board UI
│   └── static/
│       └── style.css           # Gold-on-black terminal styling
└── wmata/                      # Data collection and monitoring scripts
    ├── wmata_prediction_collector.py   # Collects and deduplicates train predictions to CSV
    ├── wmata_monitor.py                # Checks for incidents and station list changes
    ├── config.txt                      # Your API key (gitignored)
    ├── config.example.txt              # Template
    └── known_stations.json             # Station baseline for change detection (auto-created)
```

---

## Requirements

- Python 3.8+
- A free [WMATA API key](https://developer.wmata.com/)
- The following Python packages:

```
flask>=2.2
pandas>=1.5
requests>=2.31
openpyxl
```

Install with:

```bash
pip install flask pandas requests openpyxl
```

---

## Setup

**1. Clone the repo**

```bash
git clone https://github.com/yourname/metro_board.git
cd metro_board
```

**2. Configure the station board**

```bash
cp wmata_station_board/config.example.txt wmata_station_board/config.txt
```

Edit `wmata_station_board/config.txt`:

```
API_KEY=your_wmata_api_key_here
DEFAULT_STATION=Wiehle-Reston East
```

**3. Configure the monitor script**

```bash
cp wmata/config.example.txt wmata/config.txt
```

Edit `wmata/config.txt`:

```
WMATA_API_KEY=your_wmata_api_key_here
```

**4. Seed the station baseline**

On first run, `wmata_monitor.py` builds `known_stations.json` from live data so future runs only alert on actual changes:

```bash
python3 wmata/wmata_monitor.py
```

---

## Running

### Station board (manual)

```bash
python3 wmata_station_board/app.py
```

Open `http://localhost:5000` in a browser.

### Station board (systemd — Raspberry Pi)

The board runs as a systemd service on a schedule matching WMATA's operating hours:

| Day | Start | Stop |
|-----|-------|------|
| Monday – Friday | 5:00 AM | 12:00 AM |
| Saturday | 6:00 AM | 2:00 AM |
| Sunday | 6:00 AM | 12:00 AM |

```bash
sudo systemctl enable wmata_station.timer wmata_station_stop.timer
sudo systemctl start wmata_station.timer wmata_station_stop.timer
```

### Monitor script (cron)

Schedule `wmata_monitor.py` to run periodically to check for incidents and station changes:

```
*/10 * * * * /usr/bin/python3 /home/youruser/metro_board/wmata/wmata_monitor.py
```

Incidents are logged to `wmata/wmata_monitor.log`. Any new or removed stations on any line are flagged as warnings in the same log.

---

## Known Issues

### WMATA Incidents API — double-encoded characters

The WMATA Incidents API returns descriptions with incorrectly encoded characters. Smart quotes and similar Unicode characters (e.g. `'`, `"`, `–`) appear as garbled multi-character sequences like `â€™` instead of `'`.

**Root cause:** On WMATA's server, the UTF-8 bytes for these characters are read back as Windows-1252 (cp1252) and then re-serialized into the JSON response as if they were the correct characters. The result is three separate Unicode characters where one was intended.

**Workaround applied:** `app.py` and `wmata_monitor.py` reverse the mis-encoding by re-encoding each description string as cp1252 and decoding the resulting bytes as UTF-8:

```python
def _fix_wmata_encoding(s: str) -> str:
    try:
        return s.encode("cp1252").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return s
```

This correctly restores the original characters for the vast majority of incidents. If WMATA ever fixes the encoding on their end, this function will still be safe — it falls back to returning the original string on any error.

### WMATA Incidents API — vague closure data

WMATA does not expose a dedicated "station closed" boolean in the real-time API. Station closure information arrives as free-text incident descriptions with no structured fields for affected station codes. The board displays all active incidents as returned; parsing closure details from description text is out of scope.

---

## License

MIT
