import json
import random
import requests
from osrm_cache import osrm_cached_request, osrm_request_for_report
from math import radians, cos, sin, sqrt, atan2

# Parameter 
vehicle_capacity = 75
speed = 40  # km/jam
fuel_price = 10000
fuel_consumption = 13  # km/l
cost_per_km = 769
overnight_stay_cost = 100000
rest_cost = 10000
max_daily_hours = 8
max_work_hours = 3
rest_time = 0.5
nginap_time = 8  # jam
service_time_per_demand = 8 / 60 # 8 menit per demand, dikonversi ke jam
OSRM_HOST = "http://localhost:5000"
osrm_cache = {}
    
def load_input_data():
    with open("data_lokasi.json", "r") as f:
        lokasi = json.load(f)
    depots = {}
    customers = {}
    rest_areas = {}
    menginap_locs = {}

    for item in lokasi:
        if item["type"] == "depot":
            kapasitas = item.get("supply", 72)
            depots[item["name"]] = (item["lat"], item["lon"], kapasitas)
        elif item["type"] == "customer":
            customers[item["name"]] = (item["lat"], item["lon"], item["demand"], item["fee"])
        elif item["type"] == "rest_area":
            rest_areas[item["name"]] = (item["lat"], item["lon"])
        elif item["type"] == "menginap":
           menginap_locs[item["name"]] = (item["lat"], item["lon"])

    return depots, customers, rest_areas, menginap_locs


def generate_virtual_rest_area(last_coord, i=1):
    if isinstance(last_coord[0], str) and isinstance(last_coord[1], (tuple, list)):
        last_coord = last_coord[1]
    lat = float(last_coord[0])
    lon = float(last_coord[1])
    return (lat + 0.01 * i, lon + 0.01 * i)

def generate_virtual_menginap_area(last_coord, i=1):
    if isinstance(last_coord[0], str) and isinstance(last_coord[1], (tuple, list)):
        last_coord = last_coord[1]
    lat = float(last_coord[0])
    lon = float(last_coord[1])
    return (lat + 0.015 * i, lon + 0.015 * i)

def load_vehicle_count():
    try:
        with open("config.json", "r") as f:
            config = json.load(f)
            return config.get("vehicle_count", 1)
    except:
        return 1

def find_nearest_depot(customer_loc, depots):
    return min(depots.items(), key=lambda d: osrm_cached_request(customer_loc, d[1][:2])["duration_hr"])

def allocate_customers(customers, depots, vehicle_count):
    unassigned = set(customers.keys())
    assignments = []
    depot_supplies = {name: data[2] for name, data in depots.items()}
    depot_list = list(depots.items())

    for i in range(vehicle_count):
        vehicle = {
            "route": [],
            "customers": [],
            "remaining_capacity": vehicle_capacity,
            "depot_sources": []  # list of (depot_name, qty_used)
        }

        if not unassigned:
            break

        # Urutkan pelanggan berdasarkan jarak terdekat ke semua depot
        sorted_customers = sorted(unassigned, key=lambda c: min(
            osrm_cached_request(customers[c][:2], d[1][:2])["distance_km"]
            for d in depot_list
        ))

        for cust in sorted_customers:
            demand = customers[cust][2]
            if demand > vehicle["remaining_capacity"]:
                continue

            vehicle["customers"].append(cust)
            vehicle["remaining_capacity"] -= demand
            unassigned.remove(cust)

            if vehicle["remaining_capacity"] == 0:
                break

        # Total demand kendaraan ini
        total_demand = sum(customers[c][2] for c in vehicle["customers"])

        # Ambil supply dari beberapa depot sesuai kebutuhan
        remaining_need = total_demand
        for depot_name, (lat, lon, supply) in depot_list:
            if remaining_need == 0:
                break
            take = min(depot_supplies[depot_name], remaining_need)
            if take > 0:
                vehicle["depot_sources"].append((depot_name, take))
                depot_supplies[depot_name] -= take
                remaining_need -= take

        # Tentukan titik awal kendaraan dari depot pengambil supply terbesar
        if vehicle["depot_sources"]:
            primary_depot = max(vehicle["depot_sources"], key=lambda x: x[1])[0]
            vehicle["depot"] = (primary_depot, depots[primary_depot])
        else:
            vehicle["depot"] = ("Unknown", (0.0, 0.0, 0))

        assignments.append(vehicle)

    return assignments


def get_nearest_or_virtual_rest_area(current, rest_areas, counter):
    nearest = None
    min_dist = float('inf')
    for coord in rest_areas.values():
        d_result = osrm_cached_request(current, coord)
        d = d_result["distance_km"]
        if d < min_dist and d <= 10:
            nearest = coord
            min_dist = d
    return nearest if nearest else generate_virtual_rest_area(current, counter)

def get_nearest_or_virtual_menginap(current, menginap_locs, counter):
    nearest = None
    min_dist = float('inf')
    for coord in menginap_locs.values():
        d_result = osrm_cached_request(current, coord)
        d = d_result["distance_km"]
        if d < min_dist and d <= 10:
            nearest = coord
            min_dist = d
    return nearest if nearest else generate_virtual_menginap_area(current, counter)

def calculate_route_metrics(route, customers, depot, rest_areas=None, menginap_locs=None, remaining_capacity=vehicle_capacity):
    total_time = 0
    time_since_rest = 0
    time_since_menginap = 0
    total_distance = 0
    total_revenue = 0
    total_cost = 0
    rest_counter = 0
    nginap_counter = 0
    overnight_stays = 0
    total_travel_time = 0
    total_service_time = 0
    total_rest_time = 0
    total_nginap_time = 0
    vehicle_route = [depot[:2]]
    assigned = []

    for cust in route:
        demand = customers[cust][2]
        if demand > remaining_capacity:
            break  # Stop jika kapasitas tidak cukup lagi
        remaining_capacity -= demand
        cust_coord = customers[cust][:2]
        last_point = vehicle_route[-1]
        last_coord = last_point[1] if isinstance(last_point, tuple) and isinstance(last_point[0], str) else last_point

        # Hitung waktu perjalanan ke titik pelanggan
        osrm_result = osrm_cached_request(last_coord, cust_coord)
        dist = osrm_result["distance_km"]
        travel_time = osrm_result["duration_hr"]

        # Tambahkan ke waktu total dan perjalanan
        total_travel_time += travel_time
        time_since_rest += travel_time
        time_since_menginap += travel_time

        # Cek apakah perlu istirahat
        if time_since_rest >= max_work_hours:
            rest_coord = get_nearest_or_virtual_rest_area(last_coord, rest_areas, rest_counter)
            vehicle_route.append(("rest_virtual" if rest_coord not in rest_areas.values() else "rest", rest_coord))
            total_rest_time += rest_time
            total_time += rest_time
            time_since_rest = 0
            total_cost += rest_cost
            rest_counter += 1

        # Cek apakah perlu menginap
        if time_since_menginap > max_daily_hours:
            nginap_coord = get_nearest_or_virtual_menginap(last_coord, menginap_locs, nginap_counter)
            vehicle_route.append(("nginap_virtual" if nginap_coord not in menginap_locs.values() else "nginap", nginap_coord))
            total_nginap_time += nginap_time
            time_since_rest = 0
            time_since_menginap = 0
            total_cost += overnight_stay_cost
            nginap_counter += 1
            overnight_stays += 1


        # Tambahkan ke rute dan hitung waktu pelayanan
        vehicle_route.append(("customer", cust_coord))
        service_time = customers[cust][2] * service_time_per_demand
        total_service_time += service_time
        total_time += service_time
        time_since_rest += service_time
        time_since_menginap += service_time
        total_distance += dist
        total_revenue += customers[cust][3] * customers[cust][2]
        assigned.append((cust_coord, cust, service_time))
    
    total_work_time = total_travel_time + total_service_time
    total_cost += (total_distance / fuel_consumption) * fuel_price
    total_cost += total_distance * cost_per_km
    profit = total_revenue - total_cost

    return (vehicle_route, assigned, overnight_stays, round(total_distance, 2),
    round(total_revenue, 2),
    round(total_cost, 2),
    round(profit, 2),
    round(total_service_time, 2),
    round(total_rest_time, 2),
    round(total_nginap_time, 2),
    round(total_time, 2),
    round(total_travel_time, 2),
    round(total_work_time, 2)
    )

def tabu_search_vrp(depot, customer_names, customers, rest_areas=None, menginap_locs=None, iterations=500, tabu_tenure=10):
    print(f"[DEBUG] Mulai tabu search: {len(customer_names)} pelanggan")
    current_solution = customer_names[:]
    best_solution = current_solution[:]
    best_cost = calculate_route_metrics(best_solution, customers, depot, rest_areas, menginap_locs)[5]  # total cost
    tabu_list = []
    
    for _ in range(iterations):
        print(f"[DEBUG] Iterasi {_+1}/{iterations}")
        neighborhood = []
        for i in range(len(current_solution)):
            for j in range(i + 1, len(current_solution)):
                neighbor = current_solution[:]
                neighbor[i], neighbor[j] = neighbor[j], neighbor[i]
                if (i, j) not in tabu_list:
                    neighborhood.append((neighbor, (i, j)))
        if not neighborhood:
            break
        neighborhood.sort(key=lambda x: calculate_route_metrics(x[0], customers, depot, rest_areas, menginap_locs)[5])
        best_neighbor, move = neighborhood[0]
        current_solution = best_neighbor
        tabu_list.append(move)
        if len(tabu_list) > tabu_tenure:
            tabu_list.pop(0)
        cost = calculate_route_metrics(best_solution, customers, depot, rest_areas, menginap_locs)[5]
        if cost < best_cost:
            best_solution = current_solution[:]
            best_cost = cost
    return calculate_route_metrics(best_solution, customers, depot, rest_areas, menginap_locs)

def run_cmvrp(return_assignments=False):
    depots, customers, rest_areas, menginap_locs = load_input_data()
    data_lokasi = json.load(open("data_lokasi.json"))
    rest_areas = {item["name"]: (item["lat"], item["lon"]) for item in data_lokasi if item["type"] == "rest_area"}
    menginap_locs = {item["name"]: (item["lat"], item["lon"]) for item in data_lokasi if item["type"] == "menginap"}
    vehicle_count = load_vehicle_count()
    print(">>> Mulai alokasi pelanggan")
    assignments = allocate_customers(customers, depots, vehicle_count)
    print(">>> Mulai optimasi rute")
    all_routes = []
    for vehicle in assignments:
        depot_name, depot_data = vehicle["depot"]
        route_data = tabu_search_vrp(depot_data, vehicle["customers"], customers, rest_areas=rest_areas, menginap_locs=menginap_locs)
        all_routes.append(route_data)
    print(">>> Mulai generate leaflet HTML")
    generate_leaflet_html(all_routes, rest_areas, menginap_locs)
    if return_assignments:
        for idx, route in enumerate(all_routes):
            assigned_customers = route[1]
            print(f"\nRute Kendaraan {idx+1}:")
            for coord, cust, service_time in assigned_customers:
                print(f"  - {cust}: koordinat={coord}, waktu pelayanan={service_time:.2f} jam")
        return assignments
    return "vrp_tabu_search_visualisasi.html"

def generate_leaflet_html(routes, rest_areas=None, menginap_locs=None):
    scripts = []
    if rest_areas is None:
        rest_areas = {}
    if menginap_locs is None:
        menginap_locs = {}

    with open("visual_template.html", "r") as f:
        template = f.read()

    colors = ["red", "blue", "green", "orange", "purple", "brown", "magenta", "cyan", "black"]

    for idx, route_tuple in enumerate(routes):
        print(f"[DEBUG] Membuat rute untuk kendaraan {idx+1}")
        route_coords = route_tuple[0]
        color = colors[idx % len(colors)]
        route_waypoints = []

        for pt in route_coords:
            print(f"[DEBUG] Titik: {pt}")
            if isinstance(pt, (tuple, list)) and len(pt) == 2:
                # Jika pt berupa ("label", (lat, lon))
                if isinstance(pt[0], str) and isinstance(pt[1], (tuple, list)) and len(pt[1]) == 2:
                    label, coord = pt
                    lat, lon = float(coord[0]), float(coord[1])

                    if label == "rest" or label == "rest_virtual":
                        popup = "Virtual Rest Area" if label == "rest_virtual" else "Rest Area Manual"
                        scripts.append(f"""L.marker([{lat}, {lon}], {{
                            icon: L.icon({{
                                iconUrl: '/static/rest_area.png',
                                iconSize: [25, 41],
                                iconAnchor: [12, 41]
                            }})
                        }}).addTo(map).bindPopup('{popup}');""")

                    elif label == "nginap" or label == "nginap_virtual":
                        popup = "Virtual Tempat Menginap" if label == "nginap_virtual" else "Tempat Menginap Manual"
                        scripts.append(f"""L.marker([{lat}, {lon}], {{
                            icon: L.icon({{
                                iconUrl: '/static/menginap.png',
                                iconSize: [25, 41],
                                iconAnchor: [12, 41]
                            }})
                        }}).addTo(map).bindPopup('{popup}');""")

                    elif label.lower() == "depot":
                        scripts.append(f"""L.marker([{lat}, {lon}], {{
                            icon: L.icon({{
                                iconUrl: '/static/depot.png',
                                iconSize: [25, 41],
                                iconAnchor: [12, 41]
                            }})
                        }}).addTo(map).bindPopup('Depot');""")

                    elif label.lower() == "customer":
                        scripts.append(f"""L.marker([{lat}, {lon}], {{
                            icon: L.icon({{
                                iconUrl: '/static/customer.png',
                                iconSize: [25, 41],
                                iconAnchor: [12, 41]
                            }})
                        }}).addTo(map).bindPopup('Pelanggan');""")

                    # juga tambahkan sebagai waypoint
                    route_waypoints.append((lat, lon))

                # Jika titik rute hanya berupa (lat, lon)
                elif isinstance(pt[0], (float, int)) and isinstance(pt[1], (float, int)):
                    route_waypoints.append((pt[0], pt[1]))

        # Tambahkan marker pelanggan berdasarkan data `assigned_customers`
        assigned_customers = route_tuple[1]
        for coord, name, svc_time in assigned_customers:
            lat, lon = float(coord[0]), float(coord[1])
            scripts.append(f"""L.marker([{lat}, {lon}], {{
                icon: L.icon({{
                    iconUrl: '/static/customer.png',
                    iconSize: [25, 41],
                    iconAnchor: [12, 41]
                }})
            }}).addTo(map).bindPopup('{name}');""")

        # Tambahkan marker depot dari titik awal
        if route_coords:
            first = route_coords[0]
            if isinstance(first, (tuple, list)):
                if isinstance(first[0], str) and isinstance(first[1], (tuple, list)):
                    lat, lon = first[1]
                elif isinstance(first[0], (float, int)):
                    lat, lon = first
                scripts.append(f"""L.marker([{lat}, {lon}], {{
                    icon: L.icon({{
                        iconUrl: '/static/depot.png',
                        iconSize: [25, 41],
                        iconAnchor: [12, 41]
                    }})
                }}).addTo(map).bindPopup('Depot Kendaraan {idx+1}');""")

        # Routing line
        waypoints_str = ",\n".join([
            f"L.latLng({float(lat)}, {float(lon)})" for lat, lon in route_waypoints
        ])
        scripts.append(f"""
        L.Routing.control({{
            waypoints: [{waypoints_str}],
            lineOptions: {{
                styles: [{{ color: '{color}', weight: 5 }}]
            }},
            createMarker: () => null,
            routeWhileDragging: false
        }}).addTo(map);
        """)

    # Gambar marker rest_area manual
    for name, coord in rest_areas.items():
        lat, lon = float(coord[0]), float(coord[1])
        scripts.append(f"""L.marker([{lat}, {lon}], {{
            icon: L.icon({{
                iconUrl: '/static/rest_area.png',
                iconSize: [25, 41],
                iconAnchor: [12, 41]
            }})
        }}).addTo(map).bindPopup('Rest Area: {name}');""")

    # Gambar marker menginap manual
    for name, coord in menginap_locs.items():
        lat, lon = float(coord[0]), float(coord[1])
        scripts.append(f"""L.marker([{lat}, {lon}], {{
            icon: L.icon({{
                iconUrl: '/static/menginap.png',
                iconSize: [25, 41],
                iconAnchor: [12, 41]
            }})
        }}).addTo(map).bindPopup('Tempat Menginap: {name}');""")

    # Final render
    final_html = template.replace("[[ROUTES_HERE]]", "\n".join(scripts))
    with open("vrp_tabu_search_visualisasi.html", "w") as f:
        f.write(final_html)


def calculate_route_segments(route, customers, depot, rest_areas=None, menginap_locs=None):
    segments = []
    total_distance = 0
    total_time = 0
    total_cost = 0
    total_revenue = 0
    total_rest_time = 0
    total_nginap_time = 0
    total_service_time = 0
    total_travel_time = 0
    total_work_time = 0
    time_since_rest = 0
    time_since_menginap = 0
    current_loc = depot[:2]
    rest_counter = 0
    nginap_counter = 0

    for cust_name in route:
        customer = customers[cust_name]
        dest_loc = customer[:2]
        osrm_result = osrm_cached_request(current_loc, dest_loc)
        dist = osrm_result["distance_km"]
        travel_time = osrm_result["duration_hr"]
        service_time = customer[2] * service_time_per_demand
        cost = dist * cost_per_km + (dist / fuel_consumption * fuel_price)
        revenue = customer[2] * customer[3]

        # Update timers
        time_since_rest += travel_time
        time_since_menginap += travel_time
        total_travel_time += travel_time
        total_service_time += service_time

        # Cek apakah perlu ISTIRAHAT
        if time_since_rest >= max_work_hours:
            total_rest_time += rest_time
            total_time += rest_time
            total_cost += rest_cost
            segments.append({
                "from": current_loc,
                "to": current_loc,
                "customer": "Rest Area (Virtual/Manual)",
                "distance_km": 0,
                "duration_hr": 0,
                "travel_time_hr": 0,
                "service_time_hr": rest_time,
                "cost": rest_cost,
                "revenue": 0
            })
            time_since_rest = 0
            rest_counter += 1

        # Cek apakah perlu MENGINAP
        if time_since_menginap >= max_daily_hours:
            total_nginap_time += nginap_time
            total_time += nginap_time
            total_cost += overnight_stay_cost
            segments.append({
                "from": current_loc,
                "to": current_loc,
                "customer": "Menginap (Virtual/Manual)",
                "distance_km": 0,
                "duration_hr": 0,
                "travel_time_hr": 0,
                "service_time_hr": nginap_time,
                "cost": overnight_stay_cost,
                "revenue": 0
            })
            time_since_rest = 0
            time_since_menginap = 0
            nginap_counter += 1

        # Simpan segmen aktual pelanggan
        segments.append({
            "from": current_loc,
            "to": dest_loc,
            "customer": cust_name,
            "distance_km": round(dist, 2),
            "duration_hr": round(travel_time, 2),
            "travel_time_hr": round(travel_time, 2),
            "service_time_hr": round(service_time, 2),
            "cost": round(cost, 2),
            "revenue": round(revenue, 2)
        })

        total_distance += dist
        total_time += travel_time + service_time
        total_cost += cost
        total_revenue += revenue

        current_loc = dest_loc
        time_since_rest += service_time
        time_since_menginap += service_time

    total_work_time = total_travel_time + total_service_time
    total_profit = total_revenue - total_cost

    return {
        "segments": segments,
        "total_distance_km": round(total_distance, 2),
        "total_time_hr": round(total_time, 2),
        "total_cost": round(total_cost, 2),
        "total_revenue": round(total_revenue, 2),
        "profit": round(total_profit, 2),
        "total_rest_time_hr": round(total_rest_time, 2),
        "total_nginap_time_hr": round(total_nginap_time, 2),
        "total_travel_time_hr": round(total_travel_time, 2),
        "total_service_time_hr": round(total_service_time, 2),
        "total_work_time_hr": round(total_work_time, 2)
    }

def laporan_rute(routes):
    laporan = []

    for vehicle_id, data in routes.items():
        route_coords = data.get("route_coords", [])
        if not route_coords or len(route_coords) < 2:
            continue

        total_distance = 0
        total_duration = 0
        segment_list = []

        for i in range(len(route_coords) - 1):
            coord1 = route_coords[i]
            coord2 = route_coords[i + 1]
            osrm_data = osrm_request_for_report(coord1, coord2)

            segment = {
                "from": coord1,
                "to": coord2,
                "distance_km": round(osrm_data["distance_km"], 2),
                "duration_hr": round(osrm_data["duration_hr"], 2)
            }

            segment_list.append(segment)
            total_distance += osrm_data["distance_km"]
            total_duration += osrm_data["duration_hr"]

        laporan.append({
            "vehicle_id": vehicle_id,
            "total_distance_km": round(total_distance, 2),
            "total_duration_hr": round(total_duration, 2),
            "segments": segment_list
        })

    return laporan        

