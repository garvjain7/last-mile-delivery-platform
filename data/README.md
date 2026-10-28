# Test data pipeline (India / Raipur)

Builds a realistic, internally consistent dataset for developing and testing
every service (Core API, Routing Worker, Driver Gateway, Control Tower,
Simulator). The data is built as a **knowledge graph** first, checked against a
**SHACL data contract**, then loaded into Postgres and checked again with SQL
invariants.

```
OpenStreetMap ─┐
India Post PIN ─┼─► build_india_kg.py ─► world.ttl ─► validate_kg.py (SHACL) ─► kg_to_sql.py ─► Postgres ─► quality/invariants.py
Amazon LMRC  ──┤        (VROOM plans routes)            ontology/shapes.ttl
DIGIPIN  ──────┘
```

## Sources

| Source | Used for | Licence |
|---|---|---|
| OpenStreetMap, Geofabrik `central-zone` extract (2026-10-27) | Real Raipur buildings (delivery points), roads, landmarks, `addr:postcode` tags, hub sites | ODbL 1.0 — © OpenStreetMap contributors |
| India Post All-India PIN directory (Dec 2021, via [IndiaPIN](https://github.com/harshvardhaniimi/IndiaPIN)) | Which PIN codes exist; post-office names used as localities | GODL-India |
| DIGIPIN ([INDIAPOST-gov/digipin](https://github.com/INDIAPOST-gov/digipin)) | 10-character ~4 m grid code per point (`data/geo/digipin.py`) | India Post open source |
| Amazon Last Mile Routing Research Challenge 2021 | Parcel dimensions, parcels per stop, service times (`calibration/amazon_lmrc_profile.json`) | CC BY-NC 4.0 — Merchán et al., *Transportation Science* (2022) |
| VROOM (pyvroom) | Plans every route under capacity, shift, slot and vehicle-skill constraints | BSD-2 |

## What is real, measured, or assumed

- **Real:** delivery-point coordinates (OSM building centroids), street and
  landmark names, hub sites, PIN codes (only codes listed by India Post are
  accepted), DIGIPINs.
- **Measured (Amazon):** parcel size and service-time distributions,
  parcels-per-stop for apartment/commercial buildings.
- **Assumed for India (tunable in `INDIA_PROFILE`, `pipeline/build_india_kg.py`):**
  fleet mix per hub (7 two-wheelers, 2 three-wheelers, 1 van) and their
  capacities, COD share 55 %, first-attempt failure 5 % prepaid / 12 % COD,
  failure reasons, max 3 attempts then return, 12 % of parcels with delivery
  slots, urban speeds, 230 parcels/hub/day.
- **Synthetic:** people (Faker `en_IN`), merchants, house/flat numbers.
  Phone numbers are a sequential `+9190000xxxxx` block — never dial or SMS them.

## Quality checks found in the sources

- 32 India Post rows for Raipur share placeholder coordinates and 6 are
  plainly wrong (e.g. `1.22, 6.22`); they are excluded from geometry and used
  only for names.
- OSM tags PIN codes `492006` / `492007` on ~6,000 Raipur features; neither
  exists in the India Post directory, so those tags are rejected and the PIN
  is re-voted from valid neighbours (`pin_confidence`, `pin_source` record how).
- Some OSM names are spam/garbled; `clean_name()` drops them.

## Run it

```bash
# one-time downloads (git-ignored, data/raw/)
curl -L -o data/raw/osm/central-zone-261027.osm.pbf https://download.geofabrik.de/asia/india/central-zone-261027.osm.pbf
curl -L -o data/raw/pincode/pincode_india_post_2021.csv https://raw.githubusercontent.com/harshvardhaniimi/IndiaPIN/HEAD/data-raw/pincode.csv
# Amazon files: https://registry.opendata.aws/amazon-last-mile-challenges/ (only needed to re-calibrate)

python data/pipeline/extract_osm.py --pbf data/raw/osm/central-zone-261027.osm.pbf --bbox 81.53,21.15,81.75,21.33 --city raipur
python -m data.pipeline.build_india_kg --out data/build/india
python data/pipeline/validate_kg.py data/build/india/world.ttl
python data/pipeline/kg_to_sql.py data/build/india/world.ttl --url "postgresql://…/lastmile_india?sslmode=require"
python data/quality/invariants.py --url "postgresql://…/lastmile_india?sslmode=require"
```

`kg_to_sql.py` refuses to load into a database that already has orders.

## Logins (dev only)

| Who | Email | Password |
|---|---|---|
| Admin | `seed_admin@test.internal` | `AdminPass123!` |
| Everyone else | `customer001@lastmile.example.com`, `merchant1@lastmile.example.com`, `dispatch.rpr-urla@lastmile.example.com`, `fleet@lastmile.example.com`, `rider.rpr-urla.two_wheeler.1@lastmile.example.com`, … | `LastMile#2026` |

Edge-case accounts: `locked.customer@lastmile.example.com` (locked out),
`inactive.customer@lastmile.example.com` (deactivated), `rider.pending@…`,
`rider.rejected@…`, `rider.offline@…`.

## What the dataset contains (snapshot 2026-10-28 13:00 IST)

- 4 days of completed history: VROOM-planned routes per hub, delivered /
  failed attempts, failed parcels re-attempted next day, refused or
  3×-failed parcels returned.
- Today: routes in progress (some stops done, the rest `out_for_delivery`),
  plus a second wave of `pending` parcels waiting for the Routing Worker.
- Tomorrow's pipeline: `placed`, `sent` and `cancelled` orders.
- Tagged edge cases (`lm:scenario` in the graph, `merchant_order_ref` in SQL):
  bulky parcel that cannot go on a two-wheeler, parcel larger than any
  vehicle, 30-minute slot, already-expired slot, ₹48,500 COD, low-confidence
  PIN, address outside the service area, closed hub next to an active one.
