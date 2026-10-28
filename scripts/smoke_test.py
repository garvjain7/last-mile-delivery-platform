"""
End-to-end smoke test of the running platform, one role at a time.

Needs Core API (:8000) and Driver Gateway (:8002) running and the demo data
loaded (scripts/reset_demo_db.sh). Prints PASS/FAIL per step.

    python scripts/smoke_test.py               # roles, pages, order placement, tracking
    python scripts/smoke_test.py --delivery    # + routing run and a rider's deliveries
"""

import argparse
import subprocess
import sys
import uuid

import httpx

CORE, GATEWAY = "http://localhost:8000", "http://localhost:8002"  # must match PUBLIC_BASE_URL (CSRF)
DEV_PASSWORD = "LastMile#2026"
ACCOUNTS = [  # role, email, password, page it should land on
    ("admin", "seed_admin@test.internal", "AdminPass123!", "/admin"),
    ("customer", "customer001@lastmile.example.com", DEV_PASSWORD, "/users/"),
    ("merchant", "merchant1@lastmile.example.com", DEV_PASSWORD, "/merchant"),
    ("dispatcher", "dispatch.rpr-urla@lastmile.example.com", DEV_PASSWORD, "/dispatcher"),
    ("fleet manager", "fleet@lastmile.example.com", DEV_PASSWORD, "/fleet-manager"),
    ("driver", "rider.rpr-urla.two_wheeler.1@lastmile.example.com", DEV_PASSWORD, "/driver"),
]
results = []


def check(name, ok, detail=""):
    results.append(ok)
    print(f"{'PASS' if ok else 'FAIL'}  {name}{'  — ' + detail if detail else ''}")
    return ok


def login(client, email, password):
    r = client.post(f"{CORE}/auth/login", json={"email": email, "password": password})
    return r


def main(delivery):
    for svc, url in (("Core API", CORE), ("Driver Gateway", GATEWAY)):
        try:
            check(f"{svc} is up", httpx.get(f"{url}/health/live", timeout=5).status_code == 200)
        except httpx.HTTPError as exc:
            check(f"{svc} is up", False, str(exc))
            sys.exit(1)

    headers = {"Origin": CORE, "Referer": f"{CORE}/"}
    for role, email, password, landing in ACCOUNTS:
        with httpx.Client(timeout=30, headers=headers) as c:
            r = login(c, email, password)
            if not check(f"{role}: login", r.status_code == 200, f"HTTP {r.status_code}"):
                continue
            body = r.json()
            redirect = body.get("redirect_to", "")
            check(f"{role}: lands on {landing}", redirect.startswith(landing), redirect)
            page = c.get(f"{CORE}{redirect}")
            check(f"{role}: page {redirect} opens", page.status_code == 200, f"HTTP {page.status_code}")

            if role == "admin":
                ov = c.get(f"{CORE}/api/admin/overview")
                check("admin: overview data", ov.status_code == 200, f"HTTP {ov.status_code}")
                for page_name in ("orders", "warehouses", "drivers", "merchants", "users"):
                    api = c.get(f"{CORE}/api/admin/{page_name}")
                    check(f"admin: {page_name} list", api.status_code == 200, f"HTTP {api.status_code}")

            if role == "customer":
                uid = body["user_id"]
                dash = c.get(f"{CORE}/api/users/{uid}")
                check("customer: dashboard data", dash.status_code == 200, f"HTTP {dash.status_code}")
                orders = c.get(f"{CORE}/api/users/{uid}/orders")
                check("customer: order list", orders.status_code == 200, f"HTTP {orders.status_code}")
                sellers = c.get(f"{CORE}/api/users/{uid}/request/sellers").json()
                seller_list = sellers.get("sellers", sellers) if isinstance(sellers, dict) else sellers
                new = c.post(f"{CORE}/api/users/{uid}/request",
                             headers={"Idempotency-Key": str(uuid.uuid4())},
                             json={"seller_id": seller_list[0]["id"], "recipient_name": "Smoke Test",
                                   "recipient_phone": "+919000099999",
                                   "delivery_address": "Jaistambh Chowk, Raipur, Chhattisgarh",
                                   "weight_kg": 1.2, "volume_m3": 0.004})
                if check("customer: place a new order (geocoded)", new.status_code in (200, 201),
                         f"HTTP {new.status_code} {new.text[:120]}"):
                    code = new.json().get("tracking_token") or new.json().get("code")
                    track = httpx.get(f"{CORE}/api/track/{code}", timeout=10)
                    check("public: track the new order", track.status_code == 200, f"{code} HTTP {track.status_code}")

    if delivery:
        steps = [
            ("routing: plan pending parcels", [sys.executable, "-m", "services.routing_worker.app.plan_pending",
                                               "--at", "2026-10-28T13:30+05:30"]),
            ("driver: start route, deliver, fail, retry", [sys.executable, "scripts/demo_rider.py", "--deliver", "5"]),
            ("worker: record events once", [sys.executable, "-m", "services.routing_worker.app.terminal_events", "--once"]),
        ]
        for name, cmd in steps:
            p = subprocess.run(cmd, capture_output=True, text=True)
            last = (p.stdout.strip().splitlines() or [""])[-1]
            check(name, p.returncode == 0, last)
        p = subprocess.run([sys.executable, "data/quality/invariants.py"], capture_output=True, text=True)
        check("data checks after deliveries", "44/45" in p.stdout, p.stdout.strip().splitlines()[-1])

    print(f"\n{sum(results)}/{len(results)} steps passed")
    sys.exit(0 if all(results) else 1)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--delivery", action="store_true")
    main(ap.parse_args().delivery)
