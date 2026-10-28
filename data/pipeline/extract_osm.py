"""
Extract a city's real geography from an OpenStreetMap extract (ODbL).

Produces data/build/osm_<city>.json with:
  - buildings  : centroid + tags (house number, street, name, type) — delivery points
  - landmarks  : named shops/amenities/places of worship etc. — Indian addresses
                 are landmark-based ("near Hanuman Mandir"), so these matter
  - localities : named suburbs / neighbourhoods
  - streets    : named roads (for "on <road>")
  - industrial : named industrial / warehouse areas — candidate hub sites
  - postcodes  : any addr:postcode seen, with a location

Requires osmium-tool (brew install osmium-tool).

    python data/pipeline/extract_osm.py --pbf data/raw/osm/central-zone-261027.osm.pbf \
        --bbox 81.53,21.15,81.75,21.33 --city raipur
"""

import argparse
import json
import subprocess
from collections import Counter
from pathlib import Path

LANDMARK_KEYS = ("amenity", "shop", "tourism", "leisure", "healthcare", "office", "historic")


def centroid(geom):
    t, c = geom["type"], geom["coordinates"]
    if t == "Point":
        return c[1], c[0]
    ring = c[0] if t == "Polygon" else (c[0][0] if t == "MultiPolygon" else c)
    if t == "LineString":
        ring = c
    xs = [p[0] for p in ring]
    ys = [p[1] for p in ring]
    return sum(ys) / len(ys), sum(xs) / len(xs)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pbf", required=True)
    ap.add_argument("--bbox", required=True, help="minlon,minlat,maxlon,maxlat")
    ap.add_argument("--city", required=True)
    ap.add_argument("--out-dir", default="data/build")
    args = ap.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    clip = out_dir / f"{args.city}.osm.pbf"
    geojson = out_dir / f"{args.city}.geojsonseq"
    subprocess.run(["osmium", "extract", "-b", args.bbox, args.pbf, "-o", str(clip), "--overwrite"], check=True)
    subprocess.run(["osmium", "export", str(clip), "-f", "geojsonseq", "-o", str(geojson), "--overwrite",
                    "-a", "type,id"], check=True)

    buildings, landmarks, localities, streets, industrial, postcodes = [], [], [], {}, [], []
    kinds = Counter()
    with open(geojson) as fh:
        for line in fh:
            feat = json.loads(line.lstrip("\x1e"))
            tags = feat["properties"]
            geom = feat["geometry"]
            try:
                lat, lon = centroid(geom)
            except (IndexError, KeyError, ZeroDivisionError):
                continue
            ref = f"{tags.get('@type', '?')}/{tags.get('@id', '?')}"
            name = tags.get("name:en") or tags.get("name")
            if tags.get("addr:postcode"):
                postcodes.append({"postcode": tags["addr:postcode"], "lat": lat, "lon": lon})
            if tags.get("place") in ("suburb", "neighbourhood", "quarter", "locality", "village", "hamlet") and name:
                localities.append({"name": name, "kind": tags["place"], "lat": lat, "lon": lon, "osm": ref})
                kinds["locality"] += 1
                continue
            if tags.get("highway") and name and geom["type"] == "LineString":
                streets.setdefault(name, []).append([lat, lon])
                continue
            if tags.get("landuse") == "industrial" or tags.get("building") in ("warehouse", "industrial"):
                if name:
                    industrial.append({"name": name, "lat": lat, "lon": lon, "osm": ref})
            if name and any(k in tags for k in LANDMARK_KEYS) or (name and tags.get("building") == "temple"):
                kind = next((f"{k}={tags[k]}" for k in LANDMARK_KEYS if k in tags), "building=temple")
                landmarks.append({"name": name, "kind": kind, "lat": lat, "lon": lon, "osm": ref})
                kinds["landmark"] += 1
            if tags.get("building"):
                buildings.append({
                    "lat": lat, "lon": lon, "osm": ref,
                    "building": tags["building"],
                    "name": name,
                    "housenumber": tags.get("addr:housenumber"),
                    "street": tags.get("addr:street"),
                    "postcode": tags.get("addr:postcode"),
                    "levels": tags.get("building:levels"),
                })
                kinds["building"] += 1

    street_list = [{"name": n, "lat": sum(p[0] for p in pts) / len(pts), "lon": sum(p[1] for p in pts) / len(pts),
                    "points": pts[:: max(1, len(pts) // 20)]} for n, pts in streets.items()]
    result = {"city": args.city, "bbox": args.bbox, "source": Path(args.pbf).name, "license": "ODbL 1.0 (c) OpenStreetMap contributors",
              "buildings": buildings, "landmarks": landmarks, "localities": localities, "streets": street_list,
              "industrial": industrial, "postcodes": postcodes}
    out = out_dir / f"osm_{args.city}.json"
    out.write_text(json.dumps(result))
    btypes = Counter(b["building"] for b in buildings)
    print(f"buildings={len(buildings)} (named={sum(1 for b in buildings if b['name'])}, with housenumber={sum(1 for b in buildings if b['housenumber'])}, with street={sum(1 for b in buildings if b['street'])})")
    print("building types:", btypes.most_common(10))
    print(f"landmarks={len(landmarks)} localities={len(localities)} streets={len(street_list)} industrial={len(industrial)} postcodes={len(postcodes)} {Counter(p['postcode'] for p in postcodes).most_common(8)}")
    print("landmark kinds:", Counter(lm["kind"] for lm in landmarks).most_common(12))
    print("industrial:", [i["name"] for i in industrial][:20])


if __name__ == "__main__":
    main()
