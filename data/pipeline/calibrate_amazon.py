"""
Measure operational distributions from the Amazon Last Mile Routing Challenge
(all 6,112 training routes) and save them as a small, committed profile.

The India generator samples parcel sizes, service times, parcels-per-stop and
delivery-window shapes from this profile, so those properties are empirical
rather than invented. Geography, fleet and failure behaviour are India-specific
and set separately (data/pipeline/india_profile.py).

    python data/pipeline/calibrate_amazon.py --out data/calibration/amazon_lmrc_profile.json
"""

import argparse
import json
from collections import Counter
from datetime import datetime
from pathlib import Path

RAW = Path("data/raw/amazon")


def quantiles(values, n=100):
    values = sorted(values)
    return [values[min(len(values) - 1, int(i / n * len(values)))] for i in range(n + 1)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="data/calibration/amazon_lmrc_profile.json")
    args = ap.parse_args()

    routes = json.loads((RAW / "route_data.json").read_text())
    packages = json.loads((RAW / "package_data.json").read_text())

    per_stop, svc, vol, dims, win_hours = Counter(), [], [], [], []
    scan, stops_per_route = Counter(), []
    n_pk = n_win = 0
    for rid, r in routes.items():
        stops = [s for s, v in r["stops"].items() if v["type"] != "Station"]
        stops_per_route.append(len(stops))
        for sid in stops:
            pk = packages.get(rid, {}).get(sid, {})
            if not pk:
                continue
            per_stop[min(len(pk), 10)] += 1
            for p in pk.values():
                n_pk += 1
                scan[p["scan_status"]] += 1
                svc.append(p["planned_service_time_seconds"])
                d = p["dimensions"]
                sides = sorted((d["depth_cm"], d["height_cm"], d["width_cm"]))
                dims.append(sides)
                vol.append(sides[0] * sides[1] * sides[2])
                s, e = p["time_window"]["start_time_utc"], p["time_window"]["end_time_utc"]
                if isinstance(s, str):
                    a, b = datetime.fromisoformat(s), datetime.fromisoformat(e)
                    n_win += 1
                    win_hours.append(round((b - a).total_seconds() / 3600, 1))
    profile = {
        "source": "Amazon Last Mile Routing Research Challenge 2021, training set (CC BY-NC 4.0)",
        "routes": len(routes),
        "packages": n_pk,
        "stops_per_route_quantiles": quantiles(stops_per_route, 20),
        "parcels_per_stop": {str(k): v for k, v in sorted(per_stop.items())},
        "service_time_s_quantiles": quantiles(svc),
        "volume_cm3_quantiles": quantiles(vol),
        "dimensions_cm_samples": dims[:: max(1, len(dims) // 5000)],
        "window_share": n_win / n_pk,
        "window_length_hours": {str(k): v for k, v in Counter(win_hours).most_common(12)},
        "scan_status": dict(scan),
        "failure_rate": 1 - scan["DELIVERED"] / n_pk,
    }
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(profile, indent=1))
    print(json.dumps({k: v for k, v in profile.items() if k != "dimensions_cm_samples" and not k.endswith("quantiles")}, indent=1))
    print("service p10/p50/p90:", [profile["service_time_s_quantiles"][i] for i in (10, 50, 90)])
    print("volume  p10/p50/p90:", [round(profile["volume_cm3_quantiles"][i]) for i in (10, 50, 90)])


if __name__ == "__main__":
    main()
