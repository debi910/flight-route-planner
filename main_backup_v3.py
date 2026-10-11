import math
import json
import heapq
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
import pandas as pd
import networkx as nx

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Globals
G = nx.Graph()
airports = {}
restricted_zones = []
wind_cache = {}
validation_flights = []
waypoints = {}

def haversine(lat1, lon1, lat2, lon2):
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c

def calculate_bearing(lat1, lon1, lat2, lon2):
    lat1, lon1, lat2, lon2 = map(math.radians, [lat1, lon1, lat2, lon2])
    dlon = lon2 - lon1
    x = math.sin(dlon) * math.cos(lat2)
    y = math.cos(lat1) * math.sin(lat2) - (math.sin(lat1) * math.cos(lat2) * math.cos(dlon))
    initial_bearing = math.atan2(x, y)
    initial_bearing = math.degrees(initial_bearing)
    return (initial_bearing + 360) % 360

def point_line_distance(lat, lon, lat1, lon1, lat2, lon2):
    d13 = haversine(lat1, lon1, lat, lon)
    theta13 = calculate_bearing(lat1, lon1, lat, lon)
    theta12 = calculate_bearing(lat1, lon1, lat2, lon2)
    
    d_xt = math.asin(math.sin(d13 / 6371.0) * math.sin(math.radians(theta13 - theta12))) * 6371.0
    d_at = math.acos(math.cos(d13 / 6371.0) / math.cos(d_xt / 6371.0)) * 6371.0
    d12 = haversine(lat1, lon1, lat2, lon2)
    
    if 0 <= d_at <= d12:
        return abs(d_xt)
    else:
        d23 = haversine(lat2, lon2, lat, lon)
        return min(d13, d23)

def round_to_grid(lat, lon):
    return f"{round(lat / 3.0) * 3},{round(lon / 3.0) * 3}"

@app.on_event("startup")
def startup_event():
    global G, airports, restricted_zones, wind_cache, validation_flights, waypoints
    try:
        airports_df = pd.read_csv('Data/airports.csv')
        airports_df = airports_df[(airports_df['iso_country'] == 'IN') & (airports_df['type'].isin(['large_airport', 'medium_airport']))]
        
        waypoints_df = pd.read_csv('Data/waypoints.csv')
        airways_df = pd.read_csv('Data/airways.csv')
        
        with open('Data/wind_cache.json', 'r') as f:
            wind_cache = json.load(f)
            
        with open('Data/restricted_zones.json', 'r') as f:
            restricted_zones = json.load(f)
            
        with open('Data/validation_flights.json', 'r') as f:
            validation_flights = json.load(f)
    except Exception as e:
        print(f"Error loading data: {e}")
        return

    for _, row in waypoints_df.iterrows():
        waypoints[row['ident']] = {'lat': row['latitude'], 'lon': row['longitude'], 'name': row.get('name', row['ident'])}
        G.add_node(row['ident'], **waypoints[row['ident']])

    for _, row in airways_df.iterrows():
        n1 = row['from_ident']
        n2 = row['to_ident']
        if n1 in waypoints and n2 in waypoints:
            G.add_edge(n1, n2, airway_name=row['airway_name'])

    airport_nodes = {}
    for _, row in airports_df.iterrows():
        ident = row['ident']
        lat = row['latitude_deg']
        lon = row['longitude_deg']
        name = row['name']
        
        distances = []
        for wp_ident, wp_data in waypoints.items():
            dist = haversine(lat, lon, wp_data['lat'], wp_data['lon'])
            if dist <= 150:
                distances.append((dist, wp_ident))
                
        distances.sort()
        nearest_3 = distances[:3]
        
        if nearest_3:
            airport_nodes[ident] = {'lat': lat, 'lon': lon, 'name': name}
            G.add_node(ident, **airport_nodes[ident])
            for dist, wp_ident in nearest_3:
                G.add_edge(ident, wp_ident, airway_name="DIRECT")
                
    if len(G) > 0:
        largest_cc = max(nx.connected_components(G), key=len)
        G = G.subgraph(largest_cc).copy()
        airports = {k: v for k, v in airport_nodes.items() if k in G}
    
    print(f"Nodes: {G.number_of_nodes()}, Edges: {G.number_of_edges()}, Airports: {len(airports)}")

@app.get("/")
def read_index():
    return FileResponse("index.html")

@app.get("/airports")
def get_airports():
    return [{"ident": k, "name": v['name'], "lat": v['lat'], "lon": v['lon']} for k, v in airports.items()]

@app.get("/restricted-zones")
def get_restricted_zones():
    return restricted_zones

@app.get("/wind-field")
def get_wind_field():
    res = []
    for k, v in wind_cache.items():
        lat, lon = map(int, k.split(','))
        res.append({"lat": lat, "lon": lon, "speed_kmh": v['windspeed_kmh'], "from_deg": v['winddirection_deg']})
    return res

@app.get("/health")
def health():
    return {"status": "ok"}

def get_wind(lat, lon):
    key = round_to_grid(lat, lon)
    if key in wind_cache:
        return wind_cache[key]
    return {"windspeed_kmh": 0, "winddirection_deg": 0}

def is_edge_blocked(u, v, zones_list, cache, G):
    edge_key = tuple(sorted([u, v]))
    if edge_key in cache:
        return cache[edge_key]
        
    lat1, lon1 = G.nodes[u]['lat'], G.nodes[u]['lon']
    lat2, lon2 = G.nodes[v]['lat'], G.nodes[v]['lon']
    
    blocked = False
    for zone in zones_list:
        z_lat = zone['center_lat']
        z_lon = zone['center_lon']
        z_r = zone['radius_km']
        
        if point_line_distance(z_lat, z_lon, lat1, lon1, lat2, lon2) < z_r:
            blocked = True
            break
            
    cache[edge_key] = blocked
    return blocked

def run_astar(origin, destination, wind_enabled, zones_enabled, fuel_limit_enabled, custom_zones_list):
    if origin not in airports or destination not in airports:
        raise HTTPException(status_code=404, detail="Origin or destination airport not found or disconnected.")
        
    start_node = origin
    end_node = destination
    
    end_lat = G.nodes[end_node]['lat']
    end_lon = G.nodes[end_node]['lon']
    
    max_fuel = 15000
    reserve_fuel = 2000
    cruise_speed = 850
    burn_rate = 2500
    max_effective_km = (max_fuel - reserve_fuel) / burn_rate * cruise_speed if fuel_limit_enabled else float('inf')
    
    all_zones = []
    if zones_enabled:
        all_zones.extend(restricted_zones)
    all_zones.extend(custom_zones_list)
    
    blocked_cache = {}
    edges_blocked_count = set()
    
    open_set = []
    heapq.heappush(open_set, (0, start_node))
    
    came_from = {}
    
    g_score = {node: float('inf') for node in G.nodes()}
    g_score[start_node] = 0
    
    real_dist_score = {node: float('inf') for node in G.nodes()}
    real_dist_score[start_node] = 0
    
    nodes_expanded = 0
    trace = []
    
    while open_set:
        f_curr, current = heapq.heappop(open_set)
        
        # Track trace before possibly skipping due to duplicate expansion
        if len(trace) < 3000:
            c_lat = G.nodes[current]['lat']
            c_lon = G.nodes[current]['lon']
            c_name = G.nodes[current].get('name', current)
            p_lat, p_lon = None, None
            if current in came_from:
                p_node = came_from[current]
                p_lat = G.nodes[p_node]['lat']
                p_lon = G.nodes[p_node]['lon']
                
            trace.append({
                "step": nodes_expanded,
                "id": current,
                "name": c_name,
                "lat": c_lat,
                "lon": c_lon,
                "g_km": g_score[current],
                "h_km": max(0, f_curr - g_score[current]),
                "f_km": f_curr,
                "parent_lat": p_lat,
                "parent_lon": p_lon,
                "frontier_size": len(open_set)
            })
            
        nodes_expanded += 1
        
        if current == end_node:
            path = []
            curr = current
            while curr in came_from:
                path.append(curr)
                curr = came_from[curr]
            path.append(start_node)
            path.reverse()
            
            points = []
            waypoints_names = []
            legs = []
            
            total_real_km = real_dist_score[end_node]
            total_eff_km = g_score[end_node]
            
            current_real_dist = 0
            
            for i, node in enumerate(path):
                lat = G.nodes[node]['lat']
                lon = G.nodes[node]['lon']
                name = G.nodes[node].get('name', node)
                waypoints_names.append(name)
                
                alt = 11000
                if total_real_km > 0:
                    fraction = current_real_dist / total_real_km
                    if fraction <= 0.1:
                        alt = (fraction / 0.1) * 11000
                    elif fraction >= 0.9:
                        alt = ((1.0 - fraction) / 0.1) * 11000
                points.append([lon, lat, alt])
                
                if i > 0:
                    prev = path[i-1]
                    dist = haversine(G.nodes[prev]['lat'], G.nodes[prev]['lon'], lat, lon)
                    bearing = calculate_bearing(G.nodes[prev]['lat'], G.nodes[prev]['lon'], lat, lon)
                    
                    mid_lat = (G.nodes[prev]['lat'] + lat) / 2
                    mid_lon = (G.nodes[prev]['lon'] + lon) / 2
                    w = get_wind(mid_lat, mid_lon) if wind_enabled else {"windspeed_kmh": 0, "winddirection_deg": 0}
                    
                    wind_speed = w['windspeed_kmh']
                    wind_dir = w['winddirection_deg']
                    headwind_kmh = wind_speed * math.cos(math.radians(wind_dir - bearing)) if wind_enabled else 0
                    factor = max(0.7, min(1.5, 1 + headwind_kmh / 500.0)) if wind_enabled else 1.0
                    
                    current_real_dist += dist
                    eff_dist = dist * factor
                    fuel_spent = eff_dist / cruise_speed * burn_rate
                    fuel_rem = max_fuel - (g_score[node] / cruise_speed * burn_rate)
                    
                    alt_start = points[i-1][2]
                    alt_end = alt
                    
                    airway_name = G[prev][node].get('airway_name', 'DIRECT')
                    
                    legs.append({
                        "from_name": G.nodes[prev].get('name', prev),
                        "to_name": name,
                        "airway_name": airway_name,
                        "distance_km": dist,
                        "bearing_deg": bearing,
                        "wind_speed_kmh": wind_speed,
                        "wind_from_deg": wind_dir,
                        "headwind_kmh": headwind_kmh,
                        "cost_factor": factor,
                        "cumulative_km": current_real_dist,
                        "fuel_remaining_kg": fuel_rem,
                        "altitude_start_m": alt_start,
                        "altitude_end_m": alt_end
                    })
                
            estimated_time_min = total_eff_km / cruise_speed * 60 + 12 
            fuel_kg = total_eff_km / cruise_speed * burn_rate
            
            return {
                "points": points,
                "total_distance_km": total_real_km,
                "effective_km": total_eff_km,
                "estimated_time_min": estimated_time_min,
                "fuel_kg": fuel_kg,
                "waypoints": waypoints_names,
                "nodes_expanded": nodes_expanded,
                "trace": trace,
                "legs": legs,
                "edges_blocked": len([k for k, v in blocked_cache.items() if v])
            }
            
        for neighbor in G.neighbors(current):
            if is_edge_blocked(current, neighbor, all_zones, blocked_cache, G):
                continue
                
            lat1 = G.nodes[current]['lat']
            lon1 = G.nodes[current]['lon']
            lat2 = G.nodes[neighbor]['lat']
            lon2 = G.nodes[neighbor]['lon']
            
            length = haversine(lat1, lon1, lat2, lon2)
            bearing = calculate_bearing(lat1, lon1, lat2, lon2)
            
            if wind_enabled:
                mid_lat = (lat1 + lat2) / 2
                mid_lon = (lon1 + lon2) / 2
                wind = get_wind(mid_lat, mid_lon)
                wind_speed = wind['windspeed_kmh']
                wind_dir = wind['winddirection_deg']
                headwind_kmh = wind_speed * math.cos(math.radians(wind_dir - bearing))
                factor = max(0.7, min(1.5, 1 + headwind_kmh / 500.0))
            else:
                factor = 1.0
                
            effective_km = length * factor
            tentative_g_score = g_score[current] + effective_km
            
            if tentative_g_score < g_score[neighbor] and tentative_g_score <= max_effective_km:
                came_from[neighbor] = current
                g_score[neighbor] = tentative_g_score
                real_dist_score[neighbor] = real_dist_score[current] + length
                
                h = 0.7 * haversine(lat2, lon2, end_lat, end_lon) if wind_enabled else haversine(lat2, lon2, end_lat, end_lon)
                f_score = tentative_g_score + h
                
                heapq.heappush(open_set, (f_score, neighbor))
                
    raise HTTPException(status_code=404, detail="Distance too long or blocked by restricted zones.")

@app.get("/route")
def get_route_endpoint(
    origin: str, 
    destination: str, 
    wind: bool = True, 
    zones: bool = True, 
    fuel_limit: bool = True, 
    custom_zones: str = None
):
    cz_list = []
    if custom_zones:
        for z in custom_zones.split(';'):
            parts = z.split(',')
            if len(parts) == 3:
                cz_list.append({
                    "name": "Custom",
                    "center_lat": float(parts[0]),
                    "center_lon": float(parts[1]),
                    "radius_km": float(parts[2])
                })
        cz_list = cz_list[:5]
        
    res = run_astar(origin, destination, wind, zones, fuel_limit, cz_list)
    
    gc_dist = haversine(G.nodes[origin]['lat'], G.nodes[origin]['lon'], G.nodes[destination]['lat'], G.nodes[destination]['lon'])
    res['great_circle_km'] = gc_dist
    res['route_efficiency_pct'] = (res['total_distance_km'] / gc_dist - 1) * 100 if gc_dist > 0 else 0
    
    res['constraints_applied'] = {
        "wind": wind,
        "zones": zones,
        "fuel_limit": fuel_limit,
        "custom_zones_count": len(cz_list),
        "edges_blocked_by_zones": res.pop('edges_blocked')
    }
    
    if wind:
        try:
            base = run_astar(origin, destination, False, zones, fuel_limit, cz_list)
            res['baseline'] = {
                "points": base['points'],
                "total_distance_km": base['total_distance_km'],
                "estimated_time_min": base['estimated_time_min'],
                "fuel_kg": base['fuel_kg']
            }
        except HTTPException:
            res['baseline'] = None
            
    return res

@app.get("/validate")
def validate_endpoint(
    origin: str, 
    destination: str,
    wind: bool = True, 
    zones: bool = True, 
    fuel_limit: bool = True, 
    custom_zones: str = None
):
    try:
        route_info = get_route_endpoint(origin, destination, wind, zones, fuel_limit, custom_zones)
    except HTTPException:
        return {"n_flights": 0, "message": "No valid route found."}
        
    matching_flights = [f for f in validation_flights if f.get('origin') == origin and f.get('destination') == destination]
    
    if not matching_flights:
        return {"n_flights": 0, "message": "No matching flights found in validation data."}
        
    durations = [f['duration_min'] for f in matching_flights]
    real_avg = sum(durations) / len(durations)
    real_min = min(durations)
    real_max = max(durations)
    
    computed_time = route_info['estimated_time_min']
    time_error_pct = (computed_time / real_avg - 1) * 100
    
    flights_out = [{"callsign": f.get("callsign", "UNKNOWN"), "duration_min": f["duration_min"]} for f in matching_flights]
    
    real_track = None
    for f in matching_flights:
        if f.get('track'):
            real_track = f['track']
            break
            
    return {
        "computed_time_min": computed_time,
        "real_avg_duration_min": real_avg,
        "real_min": real_min,
        "real_max": real_max,
        "n_flights": len(matching_flights),
        "time_error_pct": time_error_pct,
        "route_efficiency_pct": route_info['route_efficiency_pct'],
        "real_track": real_track,
        "flights": flights_out
    }
