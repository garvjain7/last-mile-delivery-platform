"""
Build the India (Raipur) Last-Mile knowledge graph.

Sources and what each contributes
---------------------------------
OpenStreetMap (ODbL, Geofabrik central-zone extract)
    real building footprints (delivery points), named roads, landmarks,
    addr:postcode tags.
India Post PIN directory (GODL-India, via IndiaPIN mirror, Dec 2021)
    post-office names (= locality names) and coordinates; coordinates are
    quality-filtered because several Raipur rows are placeholders.
DIGIPIN (India Post algorithm, data/geo/digipin.py)
    ~4 m grid code for every point.
Amazon Last Mile Routing Challenge (CC BY-NC 4.0, data/calibration/...)
    empirical parcel dimensions, parcels-per-stop and service times.
VROOM (pyvroom)
    plans every route (capacities, shifts, time windows, vehicle skills).
India operating assumptions (INDIA_PROFILE below, labelled, tunable)
    fleet mix, COD share and amounts, failure rates/reasons, slots, speeds.

Timeline: history days (completed routes, failed parcels re-attempted next
day, refused / 3x failed parcels returned), "today" snapshot at
--snapshot-hour IST (routes in progress + a second wave waiting for the
Routing Worker), and tomorrow's pipeline (placed / sent / cancelled).

    python data/pipeline/build_india_kg.py --out data/build/india
"""

import argparse
import csv
import hashlib
import json
import math
import random
import uuid
from collections import Counter, defaultdict
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import bcrypt
import vroom
from faker import Faker
from rdflib import RDF, Graph, Literal, Namespace, URIRef
from rdflib.namespace import XSD

from data.geo import digipin

LM = Namespace("https://lastmile.example.org/ontology#")
ID = Namespace("https://lastmile.example.org/id/")
GEO = Namespace("http://www.opengis.net/ont/geosparql#")
TIME = Namespace("http://www.w3.org/2006/time#")
NS_UUID = uuid.UUID("2d6f0c1a-8e4b-4b8e-b7d3-5a1f9c0e7b21")
IST = ZoneInfo("Asia/Kolkata")

DEV_PASSWORD = "LastMile#2026"
SEED_ADMIN_EMAIL, SEED_ADMIN_PASSWORD = "seed_admin@test.internal", "AdminPass123!"

# --------------------------------------------------------------------------
# India operating assumptions. Every value here is an assumption, not a
# measurement; each is recorded in the KG/README so reviewers can challenge it.
# --------------------------------------------------------------------------
INDIA_PROFILE = {
    "hubs": [   # India Post office used to locate the hub area, hub label
        {"code": "RPR-URLA", "near_office": "Urla SO", "label": "Urla"},
        {"code": "RPR-TATI", "near_office": "Tatibandh SO", "label": "Tatibandh"},
        {"code": "RPR-MANA", "near_office": "Mana Camp SO", "label": "Mana Camp"},
    ],
    "service_radius_m": 15000,
    "fleet_per_hub": {"two_wheeler": 7, "three_wheeler": 2, "van": 1},
    "vehicle_specs": {   # max volume m3, max weight kg, avg urban speed km/h, can carry bulky
        "two_wheeler": (0.12, 25, 20.0, False),
        "three_wheeler": (1.2, 300, 16.0, True),
        "van": (3.8, 750, 15.0, True),
    },
    "max_stops_per_trip": {"two_wheeler": 35, "three_wheeler": 55, "van": 70},
    "bulky_rule": {"max_side_cm": 60, "max_weight_kg": 10},   # beyond this: not on a two-wheeler
    "shifts": [(time(8, 0), time(20, 0)), (time(9, 0), time(21, 0))],
    "planning_start": time(8, 30),
    "detour_factor": 1.35,
    # 40-70 % in published Indian estimates (Redseer, Mordor, Unicommerce 2025).
    "cod_share": 0.55,
    "cod_amount_inr_lognormal": (6.4, 0.8),        # median ~600 INR
    "slot_share": 0.12,
    "slots": [(time(9), time(13)), (time(13), time(17)), (time(17), time(21))],
    # Vendor benchmarks: NDR "healthy" < 15 %; COD return-to-origin ~26-40 %,
    # prepaid RTO < 2-5 % (Shipway FY25, Razorpay, base.com 2026). Refusal is
    # the dominant COD failure, so COD failures lean to "refused".
    "first_attempt_failure": {"prepaid": 0.06, "cod": 0.22},
    "failure_reasons": {"recipient_unavailable": 0.45, "refused": 0.35, "wrong_address": 0.15, "other": 0.05},
    "max_attempts": 3,
    "extra_service_s": {"cod": 45, "apartment": 60},
    "daily_parcels_per_hub": 230,
    "building_weight": {"apartments": 6.0, "commercial": 2.0, "house": 1.0, "yes": 1.0, "residential": 3.0},
    "excluded_buildings": {"construction", "roof", "ruins", "hut", "shed", "garage", "toilets", "transformer_tower",
                           "religious", "temple", "church", "mosque", "hospital", "school", "college", "university",
                           "train_station", "industrial", "warehouse", "government"},
}

MERCHANTS = ["Kosa Silk Studio", "Mahanadi Electronics", "Sona Kirana Store", "Bastar Crafts Collective",
             "Indravati Pharmacy", "Chhattisgarhi Rasoi Foods", "Sitar Book Depot", "Raipur Home Essentials"]
MERCHANT_WEIGHTS = [10, 22, 18, 6, 14, 12, 6, 12]


def uid(*parts):
    return uuid.uuid5(NS_UUID, "/".join(map(str, parts)))


def iri(kind, u):
    return ID[f"{kind}/{u}"]


def dt_lit(d):
    return Literal(d.astimezone(timezone.utc).isoformat(), datatype=XSD.dateTime)


def dec(x, places=4):
    return Literal(f"{x:.{places}f}", datatype=XSD.decimal)


def haversine_m(a, b):
    lat1, lon1, lat2, lon2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 2 * 6371000.0 * math.asin(math.sqrt(h))


def token(*parts):
    h = hashlib.sha256("/".join(map(str, parts)).encode()).digest()
    return "".join(chr(65 + b % 26) for b in h[:10])


class Grid:
    """Tiny spatial hash for nearest-neighbour lookups over a few thousand points."""

    def __init__(self, items, cell=0.005):
        self.cell, self.cells = cell, defaultdict(list)
        for it in items:
            self.cells[(int(it["lat"] / cell), int(it["lon"] / cell))].append(it)

    def near(self, lat, lon, radius_m, k=1):
        r = int(radius_m / 111000 / self.cell) + 1
        ci, cj = int(lat / self.cell), int(lon / self.cell)
        found = []
        for i in range(ci - r, ci + r + 1):
            for j in range(cj - r, cj + r + 1):
                for it in self.cells.get((i, j), ()):
                    d = haversine_m((lat, lon), (it["lat"], it["lon"]))
                    if d <= radius_m:
                        found.append((d, it))
        found.sort(key=lambda x: x[0])
        return found[:k]


def clean_name(name):
    if not name or len(name) < 3 or len(name) > 60:
        return None
    letters = sum(ch.isalpha() for ch in name)
    if letters < 3 or len(set(name.lower().split())) < len(name.split()) * 0.6:
        return None   # drops spammy/garbled OSM names with repeated tokens
    return " ".join(name.split())


# --------------------------------------------------------------------------
# Reference geography
# --------------------------------------------------------------------------
def _locality(office_name):
    for suffix in (" S.O", " B.O", " H.O", " SO", " BO", " HO", " PO"):
        if office_name.endswith(suffix):
            office_name = office_name[: -len(suffix)]
    return office_name.replace(" Raipur", "").strip() or "Raipur"


def load_post_offices(path, bbox):
    """India Post offices of Chhattisgarh. Returns (offices with trustworthy
    coordinates inside the city, rejected list, {pincode: [all offices]})."""
    min_lon, min_lat, max_lon, max_lat = bbox
    state = [r for r in csv.DictReader(open(path)) if r["StateName"].upper() == "CHHATTISGARH"]
    by_pin = defaultdict(list)
    for r in state:
        by_pin[r["Pincode"]].append({"office": r["OfficeName"], "locality": _locality(r["OfficeName"]),
                                     "type": r["OfficeType"], "delivery": r["Delivery"] == "Delivery"})
    rows = [r for r in state if r["District"].upper() == "RAIPUR"]
    coords = Counter((r["Latitude"], r["Longitude"]) for r in rows)
    good, rejected = [], []
    for r in rows:
        try:
            lat, lon = float(r["Latitude"]), float(r["Longitude"])
        except ValueError:
            rejected.append((r["OfficeName"], "unparseable")); continue
        if not (min_lat <= lat <= max_lat and min_lon <= lon <= max_lon):
            rejected.append((r["OfficeName"], f"outside city bbox ({lat},{lon})")); continue
        if coords[(r["Latitude"], r["Longitude"])] > 2:
            rejected.append((r["OfficeName"], "shared placeholder coordinate")); continue
        good.append({"office": r["OfficeName"], "locality": _locality(r["OfficeName"]), "pincode": r["Pincode"],
                     "lat": lat, "lon": lon})
    return good, rejected, by_pin


def locality_for_pin(pin, lat, lon, office_grid, by_pin):
    """Locality = name of a post office that serves this PIN: the nearest one
    with trustworthy coordinates, else the PIN's delivery office."""
    near = [o for d, o in office_grid.near(lat, lon, 15000, k=40) if o["pincode"] == pin]
    if near:
        return near[0]["locality"]
    offices = sorted(by_pin[pin], key=lambda o: (not o["delivery"], o["type"] != "PO", o["office"]))
    return offices[0]["locality"]


def build_address_book(osm, offices, by_pin, profile, rng):
    """Turn OSM buildings into validated Indian delivery addresses.
    A PIN is accepted only if India Post's directory lists it."""
    osm_pins = [p for p in osm["postcodes"] if len(p["postcode"]) == 6 and p["postcode"].isdigit()]
    unknown = Counter(p["postcode"] for p in osm_pins if p["postcode"] not in by_pin)
    postcode_grid = Grid([p for p in osm_pins if p["postcode"] in by_pin])
    office_grid = Grid(offices)
    landmarks = [dict(lm, name=clean_name(lm["name"])) for lm in osm["landmarks"]]
    landmark_grid = Grid([lm for lm in landmarks if lm["name"]])
    street_pts = [{"name": clean_name(s["name"]), "lat": p[0], "lon": p[1]} for s in osm["streets"] for p in s["points"]]
    street_grid = Grid([s for s in street_pts if s["name"]])
    book, stats = [], Counter()
    for b in osm["buildings"]:
        if b["building"] in profile["excluded_buildings"]:
            stats["excluded_type"] += 1; continue
        lat, lon = b["lat"], b["lon"]
        votes = postcode_grid.near(lat, lon, 1500, k=9)
        office = office_grid.near(lat, lon, 6000, k=1)
        if not office:
            stats["no_post_office_within_6km"] += 1; continue
        if votes:
            tally = Counter(v[1]["postcode"] for v in votes)
            pin, n = tally.most_common(1)[0]
            confidence = round(n / len(votes), 2)
            pin_source = "osm_addr_postcode_vote"
        else:
            pin, confidence, pin_source = office[0][1]["pincode"], 0.5, "nearest_post_office"
        if b.get("postcode") in by_pin:
            pin, confidence, pin_source = b["postcode"], 1.0, "osm_building_tag"
        elif b.get("postcode"):
            stats["building_tag_pin_not_in_india_post"] += 1
        locality = locality_for_pin(pin, lat, lon, office_grid, by_pin)
        lm = landmark_grid.near(lat, lon, 700, k=1)
        st = street_grid.near(lat, lon, 250, k=1)
        stats[f"pin_{pin_source}"] += 1
        stats["pin_conflicts_with_post_office"] += int(office[0][1]["pincode"] != pin and office[0][0] < 1500)
        book.append({
            "osm": b["osm"], "lat": lat, "lon": lon, "building": b["building"], "name": clean_name(b.get("name")),
            "levels": b.get("levels"), "housenumber": b.get("housenumber"),
            "pincode": pin, "pin_confidence": confidence, "pin_source": pin_source,
            "locality": locality,
            "landmark": lm[0][1]["name"] if lm else None, "landmark_m": round(lm[0][0]) if lm else None,
            "street": (b.get("street") or (st[0][1]["name"] if st else None)),
            "digipin": digipin.encode(lat, lon),
        })
    stats["addresses"] = len(book)
    stats["osm_postcode_tags_rejected_not_in_india_post"] = sum(unknown.values())
    stats["osm_postcodes_not_in_india_post"] = dict(unknown)
    return book, stats


def format_address(a, rng):
    parts = []
    if a["building"] == "apartments" or (a["levels"] and str(a["levels"]).isdigit() and int(a["levels"]) >= 3):
        parts.append(f"Flat {rng.randint(1, 6)}0{rng.randint(1, 4)}")
    else:
        parts.append(f"H.No. {a['housenumber'] or rng.randint(1, 240)}")
    if a["name"]:
        parts.append(a["name"])
    if a["street"]:
        parts.append(a["street"])
    if a["landmark"]:
        parts.append(f"Near {a['landmark']}")
    parts.append(a["locality"])
    parts.append(f"Raipur, Chhattisgarh {a['pincode']}")
    return ", ".join(parts)


# --------------------------------------------------------------------------
# Graph writer
# --------------------------------------------------------------------------
class KG:
    def __init__(self, seed):
        self.g = Graph()
        for p, ns in (("lm", LM), ("geo", GEO), ("time", TIME)):
            self.g.bind(p, ns)
        self.rng = random.Random(seed)
        self.fake = Faker("en_IN"); self.fake.seed_instance(seed)
        self.pw = bcrypt.hashpw(DEV_PASSWORD.encode(), bcrypt.gensalt(12)).decode()
        self.admin_pw = bcrypt.hashpw(SEED_ADMIN_PASSWORD.encode(), bcrypt.gensalt(12)).decode()
        self.phone_seq = 0
        self.stats = Counter()

    def add(self, s, p, o):
        self.g.add((s, p, o))

    def point(self, s, lat, lon):
        geom = URIRef(str(s) + "/geom")
        self.add(s, GEO.hasGeometry, geom)
        self.add(geom, GEO.asWKT, Literal(f"POINT({lon:.7f} {lat:.7f})", datatype=GEO.wktLiteral))

    def phone(self):
        # Synthetic, sequential numbers in one block; never dial or SMS them.
        self.phone_seq += 1
        return f"+9190000{self.phone_seq:05d}"

    def user(self, cls, name, email, roles, *, admin=False, active=True, locked=False, scenario=None):
        u = uid("user", email)
        s = iri("user", u)
        for p, o in ((RDF.type, cls), (LM.id, Literal(str(u))), (LM.name, Literal(name)), (LM.email, Literal(email)),
                     (LM.phone, Literal(self.phone())), (LM.isActive, Literal(active)),
                     (LM.password_hash, Literal(self.admin_pw if admin else self.pw)),
                     (LM.derivationRule, Literal("synthetic identity (Faker en_IN, seeded)"))):
            self.add(s, p, o)
        for r in roles:
            self.add(s, LM.role, Literal(r))
        if locked:
            self.add(s, LM.failed_login_count, Literal(3))
            self.add(s, LM.locked_until, dt_lit(datetime(2099, 1, 1, tzinfo=timezone.utc)))
        if scenario:
            self.add(s, LM.scenario, Literal(scenario))
        return s


def build(args):
    profile = INDIA_PROFILE
    kg = KG(args.seed)
    rng, fake = kg.rng, kg.fake
    osm = json.loads(Path(args.osm).read_text())
    cal = json.loads(Path(args.calibration).read_text())
    bbox = tuple(map(float, osm["bbox"].split(",")))
    offices, rejected_offices, by_pin = load_post_offices(args.pincodes, bbox)
    book, addr_stats = build_address_book(osm, offices, by_pin, profile, rng)
    print(f"post offices kept={len(offices)} rejected={len(rejected_offices)}; addresses={len(book)}")

    # ---------------------------------------------------------------- hubs
    office_by_name = {o["office"]: o for o in offices}
    hubs = []
    candidates = [b for b in osm["buildings"] if b["building"] in ("industrial", "warehouse", "commercial", "yes")]
    cand_grid = Grid(candidates)
    for h in profile["hubs"]:
        po = office_by_name[h["near_office"]]
        site = next((it for d, it in cand_grid.near(po["lat"], po["lon"], 2500, k=50)
                     if it["building"] in ("industrial", "warehouse", "commercial")), None)
        site = site or cand_grid.near(po["lat"], po["lon"], 2500, k=1)[0][1]
        u = uid("warehouse", h["code"])
        s = iri("warehouse", u)
        for p, o in ((RDF.type, LM.Warehouse), (LM.id, Literal(str(u))), (LM.code, Literal(h["code"])),
                     (LM.name, Literal(f"Raipur {h['label']} Hub")), (LM.isActive, Literal(True)),
                     (LM.address, Literal(f"Hub site near {po['locality']}, Raipur, Chhattisgarh {po['pincode']}")),
                     (LM.pincode, Literal(po["pincode"])), (LM.service_radius_m, Literal(profile["service_radius_m"])),
                     (LM.observedFrom, URIRef(f"https://www.openstreetmap.org/{site['osm']}")),
                     (LM.derivationRule, Literal("hub placed on a real OSM industrial/commercial building near the named India Post office"))):
            kg.add(s, p, o)
        kg.point(s, site["lat"], site["lon"])
        hubs.append({"code": h["code"], "s": s, "id": str(u), "lat": site["lat"], "lon": site["lon"]})
    # Edge case: inactive hub right next to an active one.
    u = uid("warehouse", "RPR-CLOSED")
    s = iri("warehouse", u)
    for p, o in ((RDF.type, LM.Warehouse), (LM.id, Literal(str(u))), (LM.code, Literal("RPR-CLOSED")),
                 (LM.name, Literal("Raipur Old City Hub (closed)")), (LM.isActive, Literal(False)),
                 (LM.address, Literal("Closed hub, Raipur, Chhattisgarh 492001")), (LM.pincode, Literal("492001")),
                 (LM.scenario, Literal("inactive_warehouse_must_not_be_selected")),
                 (LM.derivationRule, Literal("edge-case fixture"))):
        kg.add(s, p, o)
    kg.point(s, hubs[0]["lat"] + 0.003, hubs[0]["lon"] + 0.003)

    for a in book:   # nearest active hub (PostGIS KNN equivalent)
        d, h = min((haversine_m((a["lat"], a["lon"]), (h["lat"], h["lon"])), h) for h in hubs)
        a["hub"], a["hub_m"] = h["code"], d
    book = [a for a in book if a["hub_m"] <= profile["service_radius_m"]]
    by_hub = defaultdict(list)
    for a in book:
        by_hub[a["hub"]].append(a)

    # ---------------------------------------------------------------- people
    kg.user(LM.Admin, "Seed Admin", SEED_ADMIN_EMAIL, ["admin"], admin=True)
    merchants = []
    for i, name in enumerate(MERCHANTS):
        u = uid("merchant", name)
        s = iri("merchant", u)
        for p, o in ((RDF.type, LM.Merchant), (LM.id, Literal(str(u))), (LM.name, Literal(name)), (LM.isActive, Literal(True)),
                     (LM.email, Literal(f"ops{i + 1}@merchants.lastmile.example.com")), (LM.phone, Literal(kg.phone())),
                     (LM.derivationRule, Literal("synthetic merchant"))):
            kg.add(s, p, o)
        mu = kg.user(LM.MerchantUser, fake.name(), f"merchant{i + 1}@lastmile.example.com", ["merchant"])
        kg.add(mu, LM.memberOf, s)
        merchants.append(s)
    for h in hubs:
        d = kg.user(LM.User, fake.name(), f"dispatch.{h['code'].lower()}@lastmile.example.com", ["dispatcher"])
        kg.add(d, LM.staffOf, h["s"])
    kg.user(LM.User, fake.name(), "fleet@lastmile.example.com", ["fleet_manager"])
    customers = [kg.user(LM.Customer, fake.name(), f"customer{i + 1:03d}@lastmile.example.com", ["customer"]) for i in range(args.customers)]
    kg.user(LM.Customer, "Locked Customer", "locked.customer@lastmile.example.com", ["customer"], locked=True, scenario="login_lockout")
    kg.user(LM.Customer, "Inactive Customer", "inactive.customer@lastmile.example.com", ["customer"], active=False, scenario="inactive_account_cannot_login")

    # ---------------------------------------------------------------- fleet
    fleet = defaultdict(list)
    reg = 0
    for h in hubs:
        for vtype, n in profile["fleet_per_hub"].items():
            vol, kg_cap, speed, bulky = profile["vehicle_specs"][vtype]
            for i in range(n):
                reg += 1
                vu = uid("vehicle", h["code"], vtype, i)
                vs = iri("vehicle", vu)
                for p, o in ((RDF.type, LM.Vehicle), (LM.id, Literal(str(vu))),
                             (LM.registration_number, Literal(f"CG04{'MA' if vtype == 'two_wheeler' else 'LB'}{reg:04d}")),
                             (LM.vehicleType, LM[vtype]), (LM.max_volume_m3, dec(vol)), (LM.max_weight_kg, dec(kg_cap, 3)),
                             (LM.isActive, Literal(True)), (LM.derivationRule, Literal("India fleet assumption (INDIA_PROFILE)"))):
                    kg.add(vs, p, o)
                shift = profile["shifts"][reg % 2]
                ds = kg.user(LM.Driver, fake.name(), f"rider.{h['code'].lower()}.{vtype}.{i + 1}@lastmile.example.com", ["driver"])
                for p, o in ((LM.vehicle, vs), (LM.warehouse, h["s"]), (LM.driverStatus, Literal("available")),
                             (LM.shift_start, Literal(shift[0].isoformat(), datatype=XSD.time)),
                             (LM.shift_end, Literal(shift[1].isoformat(), datatype=XSD.time))):
                    kg.add(ds, p, o)
                fleet[h["code"]].append({"driver": ds, "vehicle": vs, "type": vtype, "vol": vol, "kg": kg_cap,
                                         "speed": speed, "bulky": bulky, "shift": shift})
    for status in ("pending", "rejected", "offline"):
        ds = kg.user(LM.Driver, fake.name(), f"rider.{status}@lastmile.example.com", ["driver"], scenario=f"driver_{status}_no_vehicle")
        kg.add(ds, LM.warehouse, hubs[0]["s"]); kg.add(ds, LM.driverStatus, Literal(status))

    # ---------------------------------------------------------------- parcels
    dims = cal["dimensions_cm_samples"]
    svc_q = cal["service_time_s_quantiles"]
    pps = cal["parcels_per_stop"]
    pps_vals, pps_w = [int(k) for k in pps], list(pps.values())
    hub_weights = {h: [profile["building_weight"].get(a["building"], 1.0) for a in addrs] for h, addrs in by_hub.items()}

    def new_parcels(hub_code, n, day):
        addrs = rng.choices(by_hub[hub_code], hub_weights[hub_code], k=n)
        out = []
        for a in addrs:
            k = rng.choices(pps_vals, pps_w)[0] if a["building"] in ("apartments", "commercial") else rng.choice([1, 1, 1, 2])
            for _ in range(min(k, 4)):
                d = sorted(rng.choice(dims))
                vol_cm3 = max(d[0] * d[1] * d[2], 200)
                wkg = round(max(0.05, vol_cm3 / 5000 * rng.uniform(0.2, 0.8)), 3)
                cod = rng.random() < profile["cod_share"]
                svc = svc_q[rng.randint(5, 95)] + (profile["extra_service_s"]["cod"] if cod else 0)
                if a["building"] == "apartments":
                    svc += profile["extra_service_s"]["apartment"]
                p = {"addr": a, "dims": d, "vol_m3": vol_cm3 / 1e6, "kg": wkg, "service_s": int(svc), "cod": cod,
                     "cod_amount": round(math.exp(rng.gauss(*profile["cod_amount_inr_lognormal"])), 0) if cod else None,
                     "bulky": d[2] > profile["bulky_rule"]["max_side_cm"] or wkg > profile["bulky_rule"]["max_weight_kg"],
                     "hub": hub_code, "merchant": rng.choices(merchants, MERCHANT_WEIGHTS)[0],
                     "customer": rng.choice(customers) if rng.random() < args.customer_share else None,
                     "attempts": 0, "events": [], "seq_key": len(kg.stats)}
                if rng.random() < profile["slot_share"]:
                    slot = rng.choice(profile["slots"])
                    p["slot"] = (slot, day)
                out.append(p)
        return out

    today = date.fromisoformat(args.today)
    snapshot = datetime.combine(today, time(args.snapshot_hour), IST)
    days = [today - timedelta(days=i) for i in range(args.history_days, 0, -1)]
    parcel_counter = 0
    all_parcels = []

    def register(p, placed):
        nonlocal parcel_counter
        parcel_counter += 1
        p["n"] = parcel_counter
        p["id"] = uid("order", "india", parcel_counter)
        p["placed_at"] = placed
        p["events"] = [("placed", placed)]
        all_parcels.append(p)

    def intake(p, receive_by):
        placed = receive_by - timedelta(hours=rng.uniform(14, 50))
        register(p, placed)
        sent = placed + timedelta(hours=rng.uniform(1, 10))
        received = min(sent + timedelta(hours=rng.uniform(3, 20)), receive_by - timedelta(minutes=20))
        received = max(received, sent + timedelta(minutes=10))
        p["events"] += [("sent", sent), ("pending", received)]

    route_records = []

    def solve_day(hub, pool, day, start_at, wave):
        """Plan one hub-day with VROOM; returns (routes, unassigned)."""
        fl = fleet[hub["code"]]
        locs = [(hub["lat"], hub["lon"])] + [(p["addr"]["lat"], p["addr"]["lon"]) for p in pool]
        speed = 18.0
        n = len(locs)
        mat = [[0] * n for _ in range(n)]
        for i in range(n):
            for j in range(i + 1, n):
                m = haversine_m(locs[i], locs[j]) * profile["detour_factor"]
                t = int(m / (speed * 1000 / 3600)) + (30 if m > 30 else 0)
                mat[i][j] = mat[j][i] = t
        t0 = datetime.combine(day, time(0), IST)
        inp = vroom.Input()
        inp.set_durations_matrix(profile="car", matrix_input=mat)
        vehicles = []
        for vi, v in enumerate(fl):
            if v.get("busy_until") and v["busy_until"] > start_at:
                continue
            sh0 = max(datetime.combine(day, v["shift"][0], IST), start_at)
            sh1 = datetime.combine(day, v["shift"][1], IST)
            if sh1 <= sh0:
                continue
            vehicles.append(vroom.Vehicle(
                id=vi + 1, start=0, end=0,
                capacity=[int(v["vol"] * 1e6), int(v["kg"] * 1000)],
                skills={1} if v["bulky"] else set(),
                time_window=vroom.TimeWindow(int((sh0 - t0).total_seconds()), int((sh1 - t0).total_seconds())),
                speed_factor=v["speed"] / speed,
                max_tasks=profile["max_stops_per_trip"][v["type"]]))
        if not vehicles:
            return [], pool
        inp.add_vehicle(vehicles)
        jobs = []
        for ji, p in enumerate(pool):
            tws = ()
            if p.get("slot") and p["slot"][1] == day:
                a = datetime.combine(day, p["slot"][0][0], IST); b = datetime.combine(day, p["slot"][0][1], IST)
                if b > start_at:
                    tws = [vroom.TimeWindow(int((max(a, start_at) - t0).total_seconds()), int((b - t0).total_seconds()))]
            jobs.append(vroom.Job(id=ji + 1, location=ji + 1, default_service=p["service_s"],
                                  delivery=[max(1, int(p["vol_m3"] * 1e6)), max(1, int(p["kg"] * 1000))],
                                  skills={1} if p["bulky"] else set(), time_windows=tws))
        inp.add_job(jobs)
        sol = inp.solve(exploration_level=args.vroom_level, nb_threads=8)
        df = sol.routes
        routes, assigned = [], set()
        for vid, grp in df.groupby("vehicle_id"):
            steps = grp.to_dict("records")
            job_steps = [s for s in steps if s["type"] == "job"]
            if not job_steps:
                continue
            v = fl[int(vid) - 1]
            stops = []
            for s in job_steps:
                p = pool[int(s["id"]) - 1]
                assigned.add(int(s["id"]) - 1)
                stops.append({"p": p, "arrival": t0 + timedelta(seconds=int(s["arrival"])),
                              "service_s": int(s["service"])})
            end = t0 + timedelta(seconds=int(steps[-1]["arrival"]))
            start = t0 + timedelta(seconds=int(steps[0]["arrival"]))
            dist = sum(haversine_m((a["p"]["addr"]["lat"], a["p"]["addr"]["lon"]), (b["p"]["addr"]["lat"], b["p"]["addr"]["lon"]))
                       for a, b in zip(stops, stops[1:])) * profile["detour_factor"]
            dist += (haversine_m((hub["lat"], hub["lon"]), (stops[0]["p"]["addr"]["lat"], stops[0]["p"]["addr"]["lon"]))
                     + haversine_m((hub["lat"], hub["lon"]), (stops[-1]["p"]["addr"]["lat"], stops[-1]["p"]["addr"]["lon"]))) * profile["detour_factor"]
            routes.append({"vehicle": v, "hub": hub, "stops": stops, "start": start, "end": end, "dist": int(dist),
                           "day": day, "wave": wave})
            v["busy_until"] = end
        unassigned = [p for i, p in enumerate(pool) if i not in assigned]
        return routes, unassigned

    def execute(route, snapshot_at=None):
        """Apply outcomes to a planned route; snapshot_at=None means fully completed."""
        rid = uid("route", route["hub"]["code"], route["day"].isoformat(), route["wave"], route["vehicle"]["type"],
                  id(route["vehicle"]) % 1000, route["start"].isoformat())
        route["id"] = rid
        assigned_at = route["start"] - timedelta(minutes=rng.uniform(15, 40))
        route["created_at"] = assigned_at
        drift = 0.0
        carry = []
        for seq, st in enumerate(route["stops"], start=1):
            p = st["p"]
            drift += rng.gauss(0, 50)
            arrived = st["arrival"] + timedelta(seconds=max(-300, min(900, drift)))
            done = arrived + timedelta(seconds=st["service_s"])
            st.update(seq=seq, arrived=arrived, done=done)
            # A parcel can only be assigned after it reached the hub.
            parcel_assigned = max(assigned_at, p["events"][-1][1] + timedelta(minutes=1))
            p["events"] += [("assigned", parcel_assigned),
                            ("out_for_delivery", max(route["start"], parcel_assigned + timedelta(minutes=1)))]
            p["attempts"] += 1
            st["stop_id"] = uid("stop", rid, p["n"])
            if snapshot_at and done > snapshot_at:
                st["status"] = "pending"
                continue
            fail_p = profile["first_attempt_failure"]["cod" if p["cod"] else "prepaid"] * (0.8 if p["attempts"] > 1 else 1)
            if p.get("force_fail") or rng.random() < fail_p:
                reason = p.get("force_fail") or rng.choices(list(profile["failure_reasons"]), list(profile["failure_reasons"].values()))[0]
                if reason == "refused" and not p["cod"]:
                    reason = "recipient_unavailable"
                st.update(status="failed", reason=reason)
                p["events"].append(("attempt_failed", done))
                if reason == "refused" or p["attempts"] >= profile["max_attempts"]:
                    p["return_due"] = done
                else:
                    carry.append(p)
            else:
                st.update(status="delivered", reason=None)
                p["events"].append(("delivered", done))
        route["status"] = "in_progress" if snapshot_at and any(s["status"] == "pending" for s in route["stops"]) else "completed"
        route_records.append(route)
        return carry

    # ---------------------------------------------------------------- simulate days
    carry_over = defaultdict(list)
    for day in days + [today]:
        is_today = day == today
        for hub in hubs:
            for v in fleet[hub["code"]]:
                v.pop("busy_until", None)
            receive_by = datetime.combine(day, profile["planning_start"], IST)
            fresh = new_parcels(hub["code"], int(profile["daily_parcels_per_hub"] * rng.uniform(0.85, 1.1)), day)
            for p in fresh:
                intake(p, receive_by)
            pool = []
            for p in carry_over[hub["code"]]:
                p["events"].append(("pending", receive_by - timedelta(minutes=rng.uniform(30, 120))))
                pool.append(p)
            for p in all_parcels:
                if p.get("return_due") and not p.get("returned") and p["hub"] == hub["code"]:
                    p["events"].append(("returned", max(p["return_due"] + timedelta(hours=2), receive_by - timedelta(hours=1))))
                    p["returned"] = True
            pool += fresh
            carry_over[hub["code"]] = []
            start_at = receive_by
            routes, left = solve_day(hub, pool, day, start_at, wave=1)
            kg.stats["vroom_unassigned"] += len(left)
            for r in routes:
                carry_over[hub["code"]] += execute(r, snapshot if is_today else None)
            if is_today:
                # Second wave: parcels that reached the hub after the morning
                # plan; they wait as `pending` for the Routing Worker.
                wave2 = new_parcels(hub["code"], int(profile["daily_parcels_per_hub"] * 0.35), day)
                for p in wave2:
                    register(p, snapshot - timedelta(hours=rng.uniform(10, 30)))
                    sent = p["placed_at"] + timedelta(hours=rng.uniform(1, 6))
                    p["events"] += [("sent", sent), ("pending", snapshot - timedelta(minutes=rng.uniform(10, 120)))]
                    p["events"].sort(key=lambda e: e[1])
                left_today = left + carry_over[hub["code"]]
                for p in left_today:
                    failed_at = p["events"][-1][1]
                    # Re-queued by the dispatcher only if there was time to do
                    # it before the snapshot; otherwise it waits as attempt_failed.
                    if p["events"][-1][0] == "attempt_failed" and failed_at < snapshot - timedelta(minutes=15):
                        requeue = failed_at + (snapshot - failed_at) * rng.uniform(0.2, 0.8)
                        p["events"].append(("pending", requeue))
            else:
                carry_over[hub["code"]] += left

    # Tomorrow's pipeline: placed / sent / cancelled.
    for hub in hubs:
        for p in new_parcels(hub["code"], 90, today + timedelta(days=1)):
            register(p, snapshot - timedelta(hours=rng.uniform(0.3, 20)))
            roll = rng.random()
            if roll < 0.45:
                p["events"].append(("sent", min(p["placed_at"] + timedelta(hours=rng.uniform(0.5, 6)), snapshot - timedelta(minutes=2))))
            elif roll < 0.53:
                p["events"].append(("cancelled", min(p["placed_at"] + timedelta(hours=rng.uniform(0.2, 3)), snapshot - timedelta(minutes=2))))
                p["scenario"] = "cancelled_before_handoff"

    # ---------------------------------------------------------------- edge cases
    edge_specs = [
        ("bulky_parcel_needs_three_wheeler_or_van", {"dims": [70, 60, 90], "kg": 22.0}),
        ("exceeds_every_vehicle_capacity", {"dims": [200, 180, 300], "kg": 900.0}),
        ("tight_30_minute_slot", {"slot": (time(14, 0), time(14, 30))}),
        ("slot_already_expired", {"slot": (time(9, 0), time(10, 0))}),
        ("high_value_cod", {"cod_amount": 48500.0}),
        ("low_pin_confidence_address", {"low_conf": True}),
        ("outside_service_area", {"far": True}),
    ]
    for scen, spec in edge_specs:
        hub = hubs[0]
        a = dict(rng.choice(by_hub[hub["code"]]))
        if spec.get("low_conf"):
            cands = [x for x in book if x["pin_confidence"] < 0.6]
            a = dict(cands[0]) if cands else a
        if spec.get("far"):
            a.update(lat=21.1896, lon=81.2849, digipin=digipin.encode(21.1896, 81.2849), landmark="Durg Railway Station",
                     locality="Durg", pincode="491001", street=None, name=None, pin_source="edge_fixture", pin_confidence=1.0)
        hub = min(hubs, key=lambda h: haversine_m((a["lat"], a["lon"]), (h["lat"], h["lon"])))
        d = sorted(spec.get("dims", [30, 20, 15]))
        p = {"addr": a, "dims": d, "vol_m3": d[0] * d[1] * d[2] / 1e6, "kg": spec.get("kg", 1.5), "service_s": 90,
             "cod": "cod_amount" in spec, "cod_amount": spec.get("cod_amount"), "bulky": True if "dims" in spec else False,
             "hub": hub["code"], "merchant": merchants[1], "customer": None, "attempts": 0, "scenario": scen}
        if "slot" in spec:
            p["slot"] = (spec["slot"], today)
        register(p, snapshot - timedelta(hours=6))
        p["events"] += [("sent", snapshot - timedelta(hours=5)), ("pending", snapshot - timedelta(hours=2))]

    # ---------------------------------------------------------------- write orders
    for p in all_parcels:
        a = p["addr"]
        s = iri("order", p["id"])
        p["s"] = s
        p["events"].sort(key=lambda e: e[1])
        dedup = []
        for st, t in p["events"]:
            if dedup and dedup[-1][0] == st:
                continue
            dedup.append((st, t))
        p["events"] = dedup
        status = dedup[-1][0]
        for pp, o in ((RDF.type, LM.Order), (LM.id, Literal(str(p["id"]))), (LM.merchant, p["merchant"]),
                      (LM.merchant_order_ref, Literal(f"RPR-{p['n']:06d}")), (LM.tracking_token, Literal(token("india", p["n"]))),
                      (LM.recipient_phone, Literal(kg.phone())),
                      (LM.delivery_address, Literal(format_address(a, rng))),
                      (LM.pincode, Literal(a["pincode"])), (LM.locality, Literal(a["locality"])),
                      (LM.digipin, Literal(a["digipin"])), (LM.pin_confidence, dec(a["pin_confidence"], 2)),
                      (LM.pin_source, Literal(a["pin_source"])),
                      (LM.weight_kg, dec(p["kg"], 3)), (LM.volume_m3, dec(p["vol_m3"])),
                      (LM.planned_service_time_s, Literal(p["service_s"])),
                      (LM.payment_mode, Literal("cod" if p["cod"] else "prepaid")),
                      (LM.status, LM[status]), (LM.created_at, dt_lit(p["placed_at"])),
                      (LM.updated_at, dt_lit(dedup[-1][1])),
                      (LM.observedFrom, URIRef(f"https://www.openstreetmap.org/{a['osm']}") if "osm" in a else LM.EdgeFixture),
                      (LM.derivationRule, Literal("location/PIN/locality/landmark from OSM + India Post; size/service from Amazon LMRC; rest INDIA_PROFILE"))):
            kg.add(s, pp, o)
        if a.get("landmark"):
            kg.add(s, LM.landmark, Literal(a["landmark"]))
        if p["cod"]:
            kg.add(s, LM.cod_amount_inr, dec(p["cod_amount"], 2))
        if p["customer"] is not None:
            kg.add(s, LM.customer, p["customer"])
            kg.add(s, LM.recipient_name, kg.g.value(p["customer"], LM.name))
        else:
            kg.add(s, LM.recipient_name, Literal(fake.name()))
        if status not in ("placed", "cancelled"):
            kg.add(s, LM.warehouse, next(h["s"] for h in hubs if h["code"] == p["hub"]))
        if p.get("scenario"):
            kg.add(s, LM.scenario, Literal(p["scenario"]))
        loc = URIRef(str(s) + "/loc")
        kg.add(loc, RDF.type, LM.DeliveryLocation)
        kg.point(loc, a["lat"], a["lon"])
        kg.add(s, LM.deliveryLocation, loc)
        if p.get("slot"):
            (a0, b0), day = p["slot"]
            win = URIRef(str(s) + "/window")
            kg.add(s, LM.window, win); kg.add(win, RDF.type, LM.DeliveryWindow)
            for prop, t, tag in ((TIME.hasBeginning, a0, "begin"), (TIME.hasEnd, b0, "end")):
                inst = URIRef(f"{win}/{tag}")
                kg.add(win, prop, inst); kg.add(inst, TIME.inXSDDateTimeStamp, dt_lit(datetime.combine(day, t, IST)))
        prev = None
        for i, (st, t) in enumerate(dedup):
            es = iri("order-event", uid("event", p["id"], i))
            kg.add(es, RDF.type, LM.OrderStatusChange); kg.add(es, LM.order, s)
            kg.add(es, LM.toStatus, LM[st]); kg.add(es, LM.occurred_at, dt_lit(t))
            kg.add(es, LM.sequenceNo, Literal(i + 1))
            if prev:
                kg.add(es, LM.fromStatus, LM[prev])
            if i == len(dedup) - 1:
                kg.add(es, LM.isLatest, Literal(True))
            prev = st
        kg.stats[f"orders_{status}"] += 1

    # ---------------------------------------------------------------- write routes
    for r in route_records:
        rs = iri("route", r["id"])
        v = r["vehicle"]
        for pp, o in ((RDF.type, LM.Route), (LM.id, Literal(str(r["id"]))), (LM.warehouse, r["hub"]["s"]),
                      (LM.driver, v["driver"]), (LM.vehicle, v["vehicle"]),
                      (LM.status, LM["route_" + r["status"]]), (LM.created_at, dt_lit(r["created_at"])),
                      (LM.started_at, dt_lit(r["start"])), (LM.total_distance_m, Literal(r["dist"])),
                      (LM.total_duration_s, Literal(int((r["end"] - r["start"]).total_seconds()))),
                      (LM.derivationRule, Literal("planned by VROOM (pyvroom) on haversine x detour travel times"))):
            kg.add(rs, pp, o)
        if r["status"] == "completed":
            kg.add(rs, LM.completed_at, dt_lit(max(r["end"], r["stops"][-1]["done"])))
        else:
            kg.g.set((v["driver"], LM.driverStatus, Literal("on_route")))
        for st in r["stops"]:
            ss = iri("route-stop", st["stop_id"])
            for pp, o in ((RDF.type, LM.RouteStop), (LM.id, Literal(str(st["stop_id"]))), (LM.route, rs),
                          (LM.order, st["p"]["s"]), (LM.sequence, Literal(st["seq"], datatype=XSD.positiveInteger)),
                          (LM.planned_arrival_at, dt_lit(st["arrival"])), (LM.status, LM["stop_" + st["status"]])):
                kg.add(ss, pp, o)
            loc = URIRef(str(ss) + "/loc")
            kg.point(loc, st["p"]["addr"]["lat"], st["p"]["addr"]["lon"])
            kg.add(ss, LM.plannedLocation, loc)
            if st["status"] != "pending":
                kg.add(ss, LM.arrived_at, dt_lit(st["arrived"])); kg.add(ss, LM.completed_at, dt_lit(st["done"]))
                at = iri("attempt", uid("attempt", st["stop_id"]))
                for pp, o in ((RDF.type, LM.DeliveryAttempt), (LM.id, Literal(str(uid("attempt", st["stop_id"])))),
                              (LM.order, st["p"]["s"]), (LM.routeStop, ss), (LM.driver, v["driver"]),
                              (LM.outcome, Literal(st["status"] if st["status"] == "delivered" else "failed")),
                              (LM.occurred_at, dt_lit(st["done"])),
                              (LM.client_event_id, Literal(str(uid("client-event", st["stop_id"]))))):
                    kg.add(at, pp, o)
                if st["status"] == "failed":
                    kg.add(ss, LM.failureReason, LM[st["reason"]]); kg.add(at, LM.failureReason, LM[st["reason"]])
        kg.stats[f"routes_{r['status']}"] += 1

    meta = {"today": args.today, "snapshot_ist": snapshot.isoformat(), "history_days": args.history_days,
            "hubs": [{k: h[k] for k in ("code", "id", "lat", "lon")} for h in hubs],
            "post_offices_kept": len(offices), "post_offices_rejected": rejected_offices,
            "address_stats": dict(addr_stats), "orders": len(all_parcels), "routes": len(route_records),
            "stats": dict(sorted(kg.stats.items())), "triples": len(kg.g), "india_profile": {k: str(v) for k, v in profile.items()}}
    return kg, meta, book


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--osm", default="data/build/osm_raipur.json")
    ap.add_argument("--pincodes", default="data/raw/pincode/pincode_india_post_2021.csv")
    ap.add_argument("--calibration", default="data/calibration/amazon_lmrc_profile.json")
    ap.add_argument("--out", default="data/build/india")
    ap.add_argument("--today", default="2026-10-28")
    ap.add_argument("--snapshot-hour", type=int, default=13)
    ap.add_argument("--history-days", type=int, default=4)
    ap.add_argument("--customers", type=int, default=80)
    ap.add_argument("--customer-share", type=float, default=0.3)
    ap.add_argument("--vroom-level", type=int, default=3)
    ap.add_argument("--seed", type=int, default=7)
    args = ap.parse_args()
    kg, meta, book = build(args)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    kg.g.serialize(out / "world.ttl", format="turtle")
    (out / "world_meta.json").write_text(json.dumps(meta, indent=1, default=str))
    (out / "address_book.json").write_text(json.dumps(book))
    print(json.dumps({k: v for k, v in meta.items() if k not in ("india_profile", "post_offices_rejected")}, indent=1, default=str))


if __name__ == "__main__":
    main()
