"""
fetch_opensky.py -- builds data/validation_flights.json from the OpenSky Network.

What it does:
  1. Logs in with your OpenSky API client (OAuth2 client-credentials).
  2. Lists recent departures from each ORIGIN airport.
  3. Keeps flights that landed at the DEST airport.
  4. Saves each real flight's ACTUAL duration (and the GPS track, if OpenSky
     provides one -- the /tracks endpoint often returns 404, so it is optional).

Output format:
  [ {"aircraft_id": "...", "callsign": "...", "origin": "VIDP", "destination": "VABB",
     "first_seen": 1700000000, "last_seen": 1700007000, "duration_min": 116.7,
     "track": [[lat, lon, timestamp], ...]   # may be an empty list
  } ]

Setup (Windows cmd, same window you run the script in):
  set OPENSKY_CLIENT_ID=xxx
  set OPENSKY_CLIENT_SECRET=yyy
Run:
  py fetch_opensky.py
"""
import json
import os
import time
import requests

# ---- EDIT THESE ----------------------------------------------------------
ROUTES = [            # (origin ICAO, destination ICAO) pairs you will demo
    ("VIDP", "VABB"),   # Delhi -> Mumbai
    ("VIDP", "VOBL"),   # Delhi -> Bengaluru
    ("VABB", "VOMM"),   # Mumbai -> Chennai
]
MAX_FLIGHTS_PER_ROUTE = 5
DAYS_BACK_START = 4     # look at departures between 4 days ago ...
DAYS_BACK_END = 1       # ... and 1 day ago (OpenSky data is batch-processed, so "today" is empty)
MAX_TRACK_FAILURES = 2  # after this many 404s, stop asking for tracks (saves time)
# --------------------------------------------------------------------------

API = "https://opensky-network.org/api"
TOKEN_URL = "https://auth.opensky-network.org/auth/realms/opensky-network/protocol/openid-connect/token"


def get_token():
    cid = os.environ.get("OPENSKY_CLIENT_ID")
    secret = os.environ.get("OPENSKY_CLIENT_SECRET")
    if not cid or not secret:
        raise SystemExit("Set OPENSKY_CLIENT_ID and OPENSKY_CLIENT_SECRET first (see top of file).")
    r = requests.post(TOKEN_URL, data={
        "grant_type": "client_credentials",
        "client_id": cid,
        "client_secret": secret,
    }, timeout=30)
    r.raise_for_status()
    return r.json()["access_token"]


def try_track(headers, fl):
    """Return a list of [lat, lon, ts] or None if OpenSky has no track."""
    t_req = min(fl["firstSeen"] + 300, fl["lastSeen"] - 60)
    tr = requests.get(f"{API}/tracks", headers=headers, timeout=60,
                      params={"icao24": fl["icao24"], "time": t_req})
    if tr.status_code != 200:
        return None
    path = tr.json().get("path") or []
    # each path point: [time, lat, lon, baro_altitude, true_track, on_ground]
    track = [[p[1], p[2], p[0]] for p in path if p[1] is not None and p[2] is not None]
    return track if len(track) >= 10 else None


def main():
    headers = {"Authorization": f"Bearer {get_token()}"}
    now = int(time.time())
    out = []
    track_failures = 0

    for origin, dest in ROUTES:
        found = 0
        for d in range(DAYS_BACK_START, DAYS_BACK_END - 1, -1):
            if found >= MAX_FLIGHTS_PER_ROUTE:
                break
            begin = now - d * 86400
            end = begin + 86400
            r = requests.get(f"{API}/flights/departure", headers=headers, timeout=60,
                             params={"airport": origin, "begin": begin, "end": end})
            if r.status_code != 200:
                print(f"{origin}: HTTP {r.status_code} {r.text[:120]}")
                continue
            for fl in r.json():
                if fl.get("estArrivalAirport") != dest or found >= MAX_FLIGHTS_PER_ROUTE:
                    continue
                duration_min = (fl["lastSeen"] - fl["firstSeen"]) / 60.0
                if not (20 <= duration_min <= 600):      # skip obviously broken records
                    continue

                track = None
                if track_failures < MAX_TRACK_FAILURES:
                    track = try_track(headers, fl)
                    if track is None:
                        track_failures += 1
                        if track_failures == MAX_TRACK_FAILURES:
                            print("  OpenSky returns no tracks for this account -> "
                                  "saving durations only from now on.")

                out.append({
                    "aircraft_id": fl["icao24"],
                    "callsign": (fl.get("callsign") or "").strip(),
                    "origin": origin,
                    "destination": dest,
                    "first_seen": fl["firstSeen"],
                    "last_seen": fl["lastSeen"],
                    "duration_min": round(duration_min, 1),
                    "track": track or [],
                })
                found += 1
                print(f"  saved {origin}->{dest} {fl['icao24']} "
                      f"{duration_min:.0f} min, track points: {len(track or [])}")
                time.sleep(0.5)
        if found == 0:
            print(f"No flights found for {origin}->{dest}. Try other airports or widen the day range.")

    os.makedirs("data", exist_ok=True)
    with open("data/validation_flights.json", "w") as f:
        json.dump(out, f)
    print(f"Saved {len(out)} flights to data/validation_flights.json")


if __name__ == "__main__":
    main()
