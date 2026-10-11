"""
fetch_wind.py -- builds data/wind_cache.json from Open-Meteo (no API key needed).

Instead of calling the API for every waypoint (thousands of calls), we sample a
coarse lat/lon GRID over your region. The backend then uses the NEAREST grid
point for any waypoint. This keeps us far under the free rate limits.

Output format: { "lat,lon": {"windspeed_kmh": float, "winddirection_deg": float} }

Run:  python fetch_wind.py
"""
import json
import os
import time
import requests

# ---- EDIT THESE ----------------------------------------------------------
# Bounding box of the region you will demo (default: India and surroundings)
LAT_MIN, LAT_MAX = 6, 38
LON_MIN, LON_MAX = 66, 100
STEP_DEG = 3            # grid spacing in degrees (smaller = more accurate, more calls)
PRESSURE_LEVEL = 200    # hPa. 200 hPa is roughly 38,600 ft (cruise altitude)
HOUR_INDEX = 12         # which hour of today's forecast to use (0-23)
BATCH = 50              # coordinates per request (Open-Meteo accepts many per call)
# --------------------------------------------------------------------------

URL = "https://api.open-meteo.com/v1/forecast"
SPEED_VAR = f"wind_speed_{PRESSURE_LEVEL}hPa"
DIR_VAR = f"wind_direction_{PRESSURE_LEVEL}hPa"


def frange(a, b, step):
    x = a
    while x <= b:
        yield x
        x += step


def main():
    points = [(lat, lon)
              for lat in frange(LAT_MIN, LAT_MAX, STEP_DEG)
              for lon in frange(LON_MIN, LON_MAX, STEP_DEG)]
    print(f"{len(points)} grid points -> {-(-len(points) // BATCH)} requests")

    cache = {}
    for i in range(0, len(points), BATCH):
        chunk = points[i:i + BATCH]
        params = {
            "latitude": ",".join(str(p[0]) for p in chunk),
            "longitude": ",".join(str(p[1]) for p in chunk),
            "hourly": f"{SPEED_VAR},{DIR_VAR}",
            "wind_speed_unit": "kmh",
            "forecast_days": 1,
        }
        for attempt in range(3):
            r = requests.get(URL, params=params, timeout=60)
            if r.status_code == 200:
                break
            print(f"  HTTP {r.status_code}, retrying... {r.text[:150]}")
            time.sleep(5 * (attempt + 1))
        else:
            raise SystemExit("Open-Meteo kept failing; try again later or reduce the grid.")

        data = r.json()
        if isinstance(data, dict):   # single location returns a dict, not a list
            data = [data]
        for p, d in zip(chunk, data):
            h = d["hourly"]
            speed = h[SPEED_VAR][HOUR_INDEX]
            direction = h[DIR_VAR][HOUR_INDEX]
            if speed is None or direction is None:
                continue
            cache[f"{p[0]},{p[1]}"] = {
                "windspeed_kmh": speed,
                "winddirection_deg": direction,   # direction wind blows FROM
            }
        print(f"  done {min(i + BATCH, len(points))}/{len(points)}")
        time.sleep(1)   # be polite to the free API

    os.makedirs("data", exist_ok=True)
    with open("data/wind_cache.json", "w") as f:
        json.dump(cache, f)
    print(f"Saved {len(cache)} entries to data/wind_cache.json")


if __name__ == "__main__":
    main()
