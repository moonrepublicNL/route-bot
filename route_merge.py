# route_merge.py
# FleetGO CSV -> genormaliseerde legs + koppeling met customers
# Schrijft Parquet (indien mogelijk) of CSV naar data/matched/

import re, json, sys, time
from pathlib import Path
from datetime import datetime
import pandas as pd

# ------------------------------------------------------
# PADCONFIG
# ------------------------------------------------------
ROOT = Path(__file__).parent.resolve()

# FleetGO CSV zoekpaden
FLEETGO_DIRS = [ROOT / "data" / "fleetgo_csv", ROOT / "fleetgo_csv"]

# Output-basismap
OUT_BASE = ROOT / "data"
OUT_BASE.mkdir(exist_ok=True)

# Altijd customers uit data/ pakken (fix)
CUSTOMERS_PATH = OUT_BASE / "customers.csv"

# Output-submappen
MATCHED_DIR = OUT_BASE / "matched"; MATCHED_DIR.mkdir(exist_ok=True)
REPORTS_DIR = OUT_BASE / "reports"; REPORTS_DIR.mkdir(exist_ok=True)

# Geocode-cache
CACHE_PATH = OUT_BASE / "geocode_cache.json"

# Optionele geocoding (requests is optioneel)
try:
    import requests
    HAVE_REQUESTS = True
except Exception:
    HAVE_REQUESTS = False

# ------------------------------------------------------
# HELPERS
# ------------------------------------------------------
def read_csv_auto(path: Path) -> pd.DataFrame:
    for enc in ("utf-8", "latin1"):
        for sep in (";", ",", "\t"):
            try:
                df = pd.read_csv(path, encoding=enc, sep=sep)
                if df.shape[1] >= 1:
                    return df
            except Exception:
                continue
    raise RuntimeError(f"Kon CSV niet lezen: {path.name}")

WEEKDAYS_NL = {"ma","di","wo","do","vr","za","zo"}

def parse_date_nl(val):
    s = str(val).strip()
    if len(s) >= 2 and s[:2].lower() in WEEKDAYS_NL:
        s = s[2:].strip()
    return pd.to_datetime(s, dayfirst=True, errors="coerce").date()

def parse_time_to_seconds(val):
    s = str(val).strip()
    if not s or s.lower() == "nan":
        return None
    parts = s.split(":")
    try:
        if len(parts) == 2:
            h, m = int(parts[0]), int(parts[1]); sec = 0
        elif len(parts) == 3:
            h, m, sec = int(parts[0]), int(parts[1]), int(parts[2])
        else:
            return None
        return h*3600 + m*60 + sec
    except Exception:
        return None

def to_meters_from_km(km_str):
    if pd.isna(km_str): return None
    s = str(km_str).replace(",", ".")
    try: return int(float(s) * 1000)
    except Exception: return None

def parse_float(val):
    if pd.isna(val): return None
    s = str(val).replace(",", ".").replace("%","").strip()
    try: return float(s)
    except Exception: return None

def split_driver(val):
    # "2 (V-435-BX Ocho)" -> ("2","V-435-BX","Ocho")
    s = str(val)
    m = re.match(r"\s*(\d+)\s*\(([^)]+)\)", s)
    if not m: return None, None, None
    driver_id = m.group(1)
    tail = m.group(2).strip()
    parts = tail.split()
    plate = parts[0] if parts else None
    bus = " ".join(parts[1:]) if len(parts) > 1 else None
    return driver_id, plate, bus

def infer_cities(van_naar):
    if pd.isna(van_naar): return None, None
    parts = [p.strip() for p in str(van_naar).split("-")]
    if len(parts) == 2: return parts[0], parts[1]
    return None, None

def normalize_postcode(pc):
    if not pc: return None
    pc = re.sub(r"\s+", "", str(pc).upper())
    m = re.match(r"^(\d{4})([A-Z]{2})$", pc) or re.search(r"(\d{4})\s*([A-Z]{2})", pc)
    if m: return f"{m.group(1)} {m.group(2)}"
    return None

def normalize_address(addr, city_hint=None, postcode_hint=None):
    if not addr or str(addr).strip().lower() in ("", "nan", "none"):
        return None
    a = " ".join(str(addr).replace("\n"," ").split())
    city = (city_hint or "").strip()
    pc_fmt = normalize_postcode(postcode_hint)
    parts = [a]
    if pc_fmt: parts.append(pc_fmt)
    parts.append(city if city else "Amsterdam")
    parts.append("NL")
    return ", ".join(parts)

def load_cache():
    if CACHE_PATH.exists():
        try: return json.loads(CACHE_PATH.read_text())
        except Exception: return {}
    return {}
def save_cache(obj):
    try: CACHE_PATH.write_text(json.dumps(obj, ensure_ascii=False, indent=2))
    except Exception: pass

GEO_CACHE = load_cache()

# ------------------------------------------------------
# CUSTOMERS MAPPING
# ------------------------------------------------------
def load_customers_mapping():
    if not CUSTOMERS_PATH.exists(): return {}
    df = read_csv_auto(CUSTOMERS_PATH)

    # normaliseer kolomnamen
    rename_map = {}
    for c in df.columns:
        cl = c.strip().lower()
        if cl in ("fulladdress","adres_vol","adres_full","address_full"): rename_map[c] = "fulladdress"
        elif cl in ("address","adres","straat","street"): rename_map[c] = "address"
        elif cl in ("nr","huisnummer","number","no"): rename_map[c] = "nr"
        elif cl in ("postcode","zip","postalcode"): rename_map[c] = "postcode"
        elif cl in ("city","stad","plaats","town"): rename_map[c] = "city"
        elif cl in ("latitude","lat"): rename_map[c] = "lat"
        elif cl in ("longitude","lon","lng"): rename_map[c] = "lon"
        elif cl in ("name","account name","account","klant","bedrijf"): rename_map[c] = "name"
    if rename_map: df = df.rename(columns=rename_map)

    def build_key(r):
        if "fulladdress" in df.columns and pd.notna(r.get("fulladdress")) and str(r.get("fulladdress")).strip():
            addr = " ".join(str(r.get("fulladdress")).split())
            if not re.search(r",\s*NL$", addr, flags=re.I): addr = addr + ", NL"
            return addr
        street = str(r.get("address","")).strip()
        nr = str(r.get("nr","")).strip()
        base = (street + (" " + nr if nr else "")).strip()
        city = r.get("city", None)
        pc   = r.get("postcode", None)
        return normalize_address(base, city, pc)

    df["addr_key"] = df.apply(build_key, axis=1)

    mapping = {}
    for _, r in df.iterrows():
        key = r.get("addr_key")
        if not key: continue
        lat = r.get("lat", None); lon = r.get("lon", None)
        try:
            lat = float(str(lat).replace(",", ".")) if pd.notna(lat) else None
            lon = float(str(lon).replace(",", ".")) if pd.notna(lon) else None
        except Exception:
            lat = lon = None
        mapping[key] = (lat, lon)
    return mapping

CUSTOMER_COORDS = load_customers_mapping()

# ------------------------------------------------------
# GEOCODING (optioneel)
# ------------------------------------------------------
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"

def geocode_online(address):
    if not HAVE_REQUESTS: return (None, None)
    params = {"q": address, "format": "json", "limit": 1, "addressdetails": 0}
    headers = {"User-Agent": "koopjesbus-route-bot/1.0 (contact: ops@example.com)"}
    try:
        r = requests.get(NOMINATIM_URL, params=params, headers=headers, timeout=10)
        r.raise_for_status()
        data = r.json()
        if not data: return None, None
        return float(data[0]["lat"]), float(data[0]["lon"])
    except Exception:
        return None, None

def geocode_cached(address):
    if not address:
        return None, None
    g = GEO_CACHE.get(address)
    # Alleen cache-hit accepteren als beide coördinaten echt bestaan
    if g and (g.get("lat") is not None and g.get("lon") is not None):
        return g["lat"], g["lon"]
    # Anders: opnieuw online geocoden
    lat, lon = geocode_online(address)
    GEO_CACHE[address] = {"lat": lat, "lon": lon}
    save_cache(GEO_CACHE)
    if HAVE_REQUESTS:
        time.sleep(1.1)  # Nominatim rate limit
    return lat, lon


def coords_for(address):
    # Tijdelijk: geen geocoding, geen requests, alleen adressen gebruiken
    return None, None


# ------------------------------------------------------
# CONVERTER
# ------------------------------------------------------
NEEDED = [
    "Datum","Rit","Start","Eind","Duur","Totale afstand (km)","Afwijking (%)","Van/naar",
    "Vertrekadres","Vertreklocatie","Bezoekadres","Bezoeklocatie","Bestuurder","Administratie"
]

def convert_one(csv_path: Path):
    df = read_csv_auto(csv_path)
    missing = [c for c in NEEDED if c not in df.columns]
    if missing: raise RuntimeError(f"{csv_path.name}: ontbrekende kolommen: {missing}")

    rows = []
    for _, row in df.iterrows():
        date = parse_date_nl(row["Datum"])
        if not date: continue

        leg = None
        try: leg = int(str(row["Rit"]).strip())
        except: pass

        start_s = parse_time_to_seconds(row["Start"])
        end_s   = parse_time_to_seconds(row["Eind"])
        dur_s   = parse_time_to_seconds(row["Duur"])
        dist_m  = to_meters_from_km(row["Totale afstand (km)"])
        dev     = parse_float(row["Afwijking (%)"])

        from_city, to_city = infer_cities(row["Van/naar"])
        from_addr = normalize_address(row["Vertrekadres"], from_city)
        to_addr   = normalize_address(row["Bezoekadres"],  to_city)

        driver_id, plate, bus = split_driver(row["Bestuurder"])
        if not bus:
            fn = csv_path.name.lower()
            if "ocho" in fn: bus = "Ocho"
            elif "rebel" in fn: bus = "Rebel"

        admin = str(row.get("Administratie","")).strip() or None

        from_lat, from_lon = coords_for(from_addr)
        to_lat, to_lon     = coords_for(to_addr)

        rows.append({
            "date": str(date),
            "route_id": f"{date}-{bus or 'Bus'}",
            "leg": leg,
            "start_s": start_s,
            "end_s": end_s,
            "duration_s": dur_s,
            "distance_m": dist_m,
            "deviation_pct": dev,
            "from_city": from_city, "to_city": to_city,
            "from_address": from_addr, "to_address": to_addr,
            "from_lat": from_lat, "from_lon": from_lon,
            "to_lat": to_lat, "to_lon": to_lon,
            "driver_id": driver_id, "vehicle_plate": plate, "bus_name": bus,
            "administration": admin,
            "source_file": csv_path.name,
        })

    out = pd.DataFrame(rows)
    if out.empty: return None, {"file": csv_path.name, "rows": 0}

    out = out.sort_values(["date","bus_name","leg"], na_position="last").reset_index(drop=True)

    rep = {
        "file": csv_path.name,
        "rows": int(len(out)),
        "date_min": str(out["date"].min()),
        "date_max": str(out["date"].max()),
        "buses": sorted([b for b in out["bus_name"].dropna().unique()]),
        "missing_coords": int(out[ out["from_lat"].isna() | out["to_lat"].isna() ].shape[0]),
    }

    date_min, date_max = out["date"].min(), out["date"].max()
    out_path_parquet = MATCHED_DIR / f"{date_min}_to_{date_max}.parquet"
    try:
        out.to_parquet(out_path_parquet, index=False)
        written = str(out_path_parquet)
    except Exception:
        out_path_csv = MATCHED_DIR / f"{date_min}_to_{date_max}.csv"
        out.to_csv(out_path_csv, index=False)
        written = str(out_path_csv)

    rep_path = REPORTS_DIR / f"report_{date_min}_to_{date_max}.json"
    try:
        rep_path.write_text(json.dumps(rep, ensure_ascii=False, indent=2))
    except Exception:
        pass

    return written, rep

# ------------------------------------------------------
# MAIN
# ------------------------------------------------------
def main():
    # verzamel CSV's uit beide mogelijke mappen
    csvs = []
    for d in FLEETGO_DIRS:
        if d.exists():
            csvs += list(d.glob("*.csv"))
    csvs = sorted(csvs)

    if not csvs:
        print(f"Geen CSV’s gevonden in: {', '.join(str(d) for d in FLEETGO_DIRS)}")
        sys.exit(1)

    # log welke customers gebruikt wordt
    print(f"Customers file: {CUSTOMERS_PATH} (bestaat={CUSTOMERS_PATH.exists()})")

    written, reports = [], []
    for c in csvs:
        try:
            w, r = convert_one(c)
            if w: written.append(w)
            if r: reports.append(r)
        except Exception as e:
            print(f"Fout in {c.name}: {e}")

    save_cache(GEO_CACHE)

    if written:
        print("Geschreven bestanden:")
        for w in written: print(f"- {w}")
    if reports:
        print("\nKorte rapportage:")
        for r in reports:
            print(f"- {r.get('file')}: rows={r.get('rows')} range={r.get('date_min')}..{r.get('date_max')} buses={r.get('buses')} missing_coords={r.get('missing_coords')}")

if __name__ == "__main__":
    main()
