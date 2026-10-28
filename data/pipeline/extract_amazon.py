"""
Step 1 — extract a city slice of the Amazon Last Mile Routing Challenge data.

Input  (downloaded, git-ignored): data/raw/amazon/{route_data,package_data,actual_sequences}.json
Output (small, reviewable):       data/build/amazon_<prefix>.json

The raw package file uses bare NaN tokens (not strict JSON), so it is read
with Python's json module, which accepts them.

    python data/pipeline/extract_amazon.py --stations DSE --out data/build/amazon_seattle.json
"""

import argparse
import json
import math
from pathlib import Path

RAW = Path("data/raw/amazon")


def _clean(value):
    return None if isinstance(value, float) and math.isnan(value) else value


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--stations", default="DSE", help="station_code prefix, e.g. DSE (Seattle)")
    parser.add_argument("--out", default="data/build/amazon_seattle.json")
    args = parser.parse_args()

    routes = json.loads((RAW / "route_data.json").read_text())
    keep = {rid for rid, r in routes.items() if r["station_code"].startswith(args.stations)}
    sequences = json.loads((RAW / "actual_sequences.json").read_text())
    packages = json.loads((RAW / "package_data.json").read_text())

    out = {}
    for rid in sorted(keep):
        r = routes[rid]
        pk = packages.get(rid, {})
        out[rid] = {
            "station_code": r["station_code"],
            "date": r["date_YYYY_MM_DD"],
            "departure_time_utc": r["departure_time_utc"],
            "executor_capacity_cm3": r["executor_capacity_cm3"],
            "route_score": r["route_score"],
            "stops": {
                sid: {
                    "lat": s["lat"], "lng": s["lng"], "type": s["type"],
                    "zone_id": _clean(s.get("zone_id")),
                    "actual_position": sequences[rid]["actual"][sid],
                    "packages": {
                        pid: {
                            "scan_status": p.get("scan_status"),
                            "window_start_utc": _clean(p["time_window"]["start_time_utc"]),
                            "window_end_utc": _clean(p["time_window"]["end_time_utc"]),
                            "planned_service_time_seconds": p["planned_service_time_seconds"],
                            "depth_cm": p["dimensions"]["depth_cm"],
                            "height_cm": p["dimensions"]["height_cm"],
                            "width_cm": p["dimensions"]["width_cm"],
                        }
                        for pid, p in pk.get(sid, {}).items()
                    },
                }
                for sid, s in r["stops"].items()
            },
        }
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(out))
    print(f"wrote {len(out)} routes -> {args.out}")


if __name__ == "__main__":
    main()
