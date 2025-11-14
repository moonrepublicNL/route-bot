import csv
import json
from pathlib import Path
from collections import defaultdict

BASE = Path(__file__).parent
INPUT_CSV = BASE / "data" / "matched" / "2024-11-01_to_2025-11-11.csv"
OUTPUT_JSON = BASE / "data" / "routes_training.json"

def load_legs(path: Path):
    legs = []
    with path.open("r", encoding="utf-8", newline="") as f:
        r = csv.DictReader(f)
        for row in r:
            # minimale velden die we nodig hebben
            date = row.get("date")
            route_id = row.get("route_id")
            leg = row.get("leg")
            bus = row.get("bus_name")
            from_addr = row.get("from_address")
            to_addr = row.get("to_address")
            dist = row.get("distance_m")
            dur = row.get("duration_s")

            try:
                leg = int(leg) if leg not in (None, "", "nan") else None
            except:
                leg = None

            try:
                dist = int(float(dist)) if dist not in (None, "", "nan") else None
            except:
                dist = None

            try:
                dur = int(float(dur)) if dur not in (None, "", "nan") else None
            except:
                dur = None

            legs.append({
                "date": date,
                "route_id": route_id,
                "leg": leg,
                "bus_name": bus,
                "from_address": from_addr,
                "to_address": to_addr,
                "distance_m": dist,
                "duration_s": dur,
            })
    return legs

def build_routes(legs):
    # groepeer per route_id
    per_route = defaultdict(list)
    for leg in legs:
        rid = leg["route_id"]
        if not rid:
            continue
        per_route[rid].append(leg)

    routes = []
    for rid, items in per_route.items():
        # sorteer op leg-nummer
        items = sorted(items, key=lambda x: (x["date"], x["leg"] if x["leg"] is not None else 999999))

        if not items:
            continue

        date = items[0]["date"]
        bus = items[0]["bus_name"]

        # reconstructie van stops: start = eerste from_address
        stops = []
        # eerste stop
        first_from = items[0]["from_address"]
        if first_from:
            stops.append({
                "index": 0,
                "address": first_from,
                "from_leg": None,
                "to_leg": items[0]["leg"],
                "distance_from_prev": None,
                "duration_from_prev": None,
            })

        # volgende stops komen van to_address van elke leg
        idx = 1
        prev_addr = first_from
        for leg in items:
            addr = leg["to_address"]
            if not addr:
                continue
            # als dezelfde als vorige, sla over
            if addr == prev_addr:
                continue
            stops.append({
                "index": idx,
                "address": addr,
                "from_leg": leg["leg"],
                "to_leg": None,
                "distance_from_prev": leg["distance_m"],
                "duration_from_prev": leg["duration_s"],
            })
            prev_addr = addr
            idx += 1

        if len(stops) < 2:
            # te weinig nuttige stops, overslaan
            continue

        routes.append({
            "date": date,
            "route_id": rid,
            "bus_name": bus,
            "num_stops": len(stops),
            "stops": stops,
        })

    return routes

def main():
    if not INPUT_CSV.exists():
        print(f"Input CSV niet gevonden: {INPUT_CSV}")
        return

    print(f"Lees legs uit: {INPUT_CSV}")
    legs = load_legs(INPUT_CSV)
    print(f"Aantal legs: {len(legs)}")

    print("Bouw routes...")
    routes = build_routes(legs)
    print(f"Aantal routes: {len(routes)}")

    print(f"Schrijf naar: {OUTPUT_JSON}")
    with OUTPUT_JSON.open("w", encoding="utf-8") as f:
        json.dump(routes, f, ensure_ascii=False, indent=2)

    print("Klaar.")

if __name__ == "__main__":
    main()
