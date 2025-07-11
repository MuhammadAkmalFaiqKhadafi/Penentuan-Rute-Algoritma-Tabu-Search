import requests
import json
import os
import time

# Konstanta
speed = 40  # km/jam (untuk fallback, jika diperlukan)
OSRM_URL = "http://router.project-osrm.org/route/v1/driving"
CACHE_FILE = "osrm_cache.json"

# Inisialisasi cache dari file
if os.path.exists(CACHE_FILE):
    with open(CACHE_FILE, "r") as f:
        try:
            cache = json.load(f)
        except json.JSONDecodeError:
            cache = {}
else:
    cache = {}

def normalize_coord(coord):
    """Ambil koordinat dari ("nama", (lat, lon)) → (lat, lon)"""
    if isinstance(coord[0], str) and isinstance(coord[1], (tuple, list)):
        coord = coord[1]
    return (float(coord[0]), float(coord[1]))

def osrm_cached_request(coord1, coord2):
    coord1 = normalize_coord(coord1)
    coord2 = normalize_coord(coord2)
    key = f"{coord1}-{coord2}"
    
    # Cek cache
    if key in cache:
        return cache[key]

    # Buat permintaan ke OSRM
    url = f"{OSRM_URL}/{coord1[1]},{coord1[0]};{coord2[1]},{coord2[0]}?overview=false"
    try:
        response = requests.get(url)
        if response.status_code == 200:
            data = response.json()
            if data['routes']:
                route = data['routes'][0]
                result = {
                    "distance_km": route['distance'] / 1000,
                    "duration_hr": route['duration'] / 3600
                }
                cache[key] = result
                with open(CACHE_FILE, "w") as f:
                    json.dump(cache, f)
                time.sleep(0.1)  # delay untuk menghindari overlimit
                return result
    except Exception as e:
        print(f"[OSRM ERROR] {e}")

    # Fallback jika error
    return {"distance_km": 0, "duration_hr": 0}

def osrm_request_for_report(coord1, coord2):
    cache_file = "osrm_report_cache.json"
    try:
        if os.path.exists(cache_file):
            with open(cache_file, "r") as f:
                report_cache = json.load(f)
        else:
            report_cache = {}
    except:
        report_cache = {}

    coord1 = normalize_coord(coord1)
    coord2 = normalize_coord(coord2)
    key = f"{coord1}-{coord2}"

    if key in report_cache:
        return report_cache[key]

    url = f"{OSRM_URL}/{coord1[1]},{coord1[0]};{coord2[1]},{coord2[0]}?overview=false"
    try:
        response = requests.get(url)
        if response.status_code == 200:
            data = response.json()
            if data['routes']:
                route = data['routes'][0]
                result = {
                    "distance_km": route['distance'] / 1000,
                    "duration_hr": route['duration'] / 3600
                }
                report_cache[key] = result
                with open(cache_file, "w") as f:
                    json.dump(report_cache, f)
                time.sleep(0.1)
                return result
    except Exception as e:
        print(f"[OSRM REPORT ERROR] {e}")

    return {"distance_km": 0, "duration_hr": 0}

def clear_osrm_cache():
    global cache
    cache = {}
    with open(CACHE_FILE, "w") as f:
        json.dump({}, f)
    print("[CACHE] OSRM cache berhasil direset.")
