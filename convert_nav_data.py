"""
convert_nav_data.py -- converts the X-Plane airway file into the two CSVs the app needs.

Your earth_awy.dat is the old "640" format, where every line already carries the
coordinates of both waypoints:

    IDENT1  lat1  lon1  IDENT2  lat2  lon2  TYPE(1 low/2 high)  BASE  TOP  AIRWAY[-AIRWAY...]

so only earth_awy.dat is needed (earth_fix.dat / earth_nav.dat are not used).

Reads  (from the Data folder):  earth_awy.dat
Writes (to the same folder):    waypoints.csv, airways.csv

  waypoints.csv : ident, name, latitude, longitude
      ident = UNIQUE id "NAME_lat_lon" (waypoint names repeat around the world)
  airways.csv   : from_ident, to_ident, airway_name, base_fl, top_fl
      from_ident / to_ident use the same unique ids as waypoints.csv

Only segments with BOTH ends inside the bounding box below are kept.
Every segment is treated as flyable in both directions (simplification).

Run from D:\\AI Project:   py convert_nav_data.py
Optional: py convert_nav_data.py "path\\to\\folder"
"""
import csv
import os
import sys

# ---- EDIT THESE (should match the region of your wind data) ---------------
LAT_MIN, LAT_MAX = 4, 40
LON_MIN, LON_MAX = 64, 102
# --------------------------------------------------------------------------

DATA_DIR = sys.argv[1] if len(sys.argv) > 1 else "Data"


def in_box(lat, lon):
    return LAT_MIN <= lat <= LAT_MAX and LON_MIN <= lon <= LON_MAX


def node_id(name, lat, lon):
    return f"{name}_{lat:.3f}_{lon:.3f}"


def main():
    path = os.path.join(DATA_DIR, "earth_awy.dat")
    if not os.path.exists(path):
        raise SystemExit(f"Missing file: {path}")

    nodes = {}      # node_id -> (name, lat, lon)
    edges = set()   # (lo_id, hi_id, airway, base, top)
    total = 0

    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            p = line.split()
            if len(p) < 10 or p[6] not in ("1", "2"):
                continue
            try:
                lat1, lon1 = float(p[1]), float(p[2])
                lat2, lon2 = float(p[4]), float(p[5])
            except ValueError:
                continue
            total += 1
            if not (in_box(lat1, lon1) and in_box(lat2, lon2)):
                continue
            a = node_id(p[0], lat1, lon1)
            b = node_id(p[3], lat2, lon2)
            if a == b:
                continue
            nodes[a] = (p[0], lat1, lon1)
            nodes[b] = (p[3], lat2, lon2)
            lo, hi = sorted((a, b))
            edges.add((lo, hi, p[9], p[7], p[8]))

    print(f"Airway segments read: {total}, kept inside region: {len(edges)}")
    if not edges:
        raise SystemExit("No segments inside the region. Check LAT/LON limits at the top of the script.")

    wp_path = os.path.join(DATA_DIR, "waypoints.csv")
    with open(wp_path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["ident", "name", "latitude", "longitude"])
        for nid in sorted(nodes):
            name, lat, lon = nodes[nid]
            w.writerow([nid, name, lat, lon])

    aw_path = os.path.join(DATA_DIR, "airways.csv")
    with open(aw_path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["from_ident", "to_ident", "airway_name", "base_fl", "top_fl"])
        for e in sorted(edges):
            w.writerow(e)

    print(f"Wrote {len(nodes)} waypoints -> {wp_path}")
    print(f"Wrote {len(edges)} airways   -> {aw_path}")


if __name__ == "__main__":
    main()
