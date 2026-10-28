"""
Step 4 — materialise a validated knowledge graph into Postgres.

The graph is the source of truth: every row below is read from RDF facts
(lm: property local names match schema.sql columns), nothing is invented here.
Loads into an EMPTY database built from schema.sql; refuses a database that
already has orders, so it can never overwrite real data.

    python data/pipeline/kg_to_sql.py data/build/india/world.ttl --url postgresql://.../lastmile_india
"""

import argparse
import asyncio
import time

import asyncpg
from rdflib import RDF, Graph, Namespace

LM = Namespace("https://lastmile.example.org/ontology#")
GEO = Namespace("http://www.opengis.net/ont/geosparql#")
TIME = Namespace("http://www.w3.org/2006/time#")


class Reader:
    def __init__(self, g):
        self.g = g

    def v(self, s, p, cast=None):
        o = self.g.value(s, p)
        if o is None:
            return None
        o = o.toPython()
        return cast(o) if cast else o

    def id(self, s):
        return self.v(s, LM.id) if s is not None else None

    def ref(self, s, p):
        return self.id(self.g.value(s, p))

    def local(self, s, p):
        o = self.g.value(s, p)
        return None if o is None else str(o).split("#")[-1]

    def wkt(self, s, p=None):
        node = self.g.value(s, p) if p else s
        return str(self.g.value(self.g.value(node, GEO.hasGeometry), GEO.asWKT))

    def of(self, cls):
        return sorted(set(self.g.subjects(RDF.type, cls)))


def rows(g):
    r = Reader(g)
    out = {}
    users = [s for cls in (LM.Admin, LM.Customer, LM.Driver, LM.MerchantUser, LM.User) for s in r.of(cls)]
    out["users"] = [(r.id(s), r.v(s, LM.email), r.v(s, LM.phone), r.v(s, LM.password_hash), r.v(s, LM.name),
                     r.v(s, LM.isActive), r.v(s, LM.failed_login_count) or 0, r.v(s, LM.locked_until)) for s in users]
    out["user_roles"] = [(r.id(s), str(role)) for s in users for role in g.objects(s, LM.role)]
    out["merchants"] = [(r.id(s), r.v(s, LM.name), r.v(s, LM.email), r.v(s, LM.phone), r.v(s, LM.isActive)) for s in r.of(LM.Merchant)]
    out["merchant_members"] = [(r.id(s), r.ref(s, LM.memberOf)) for s in users if g.value(s, LM.memberOf)]
    out["warehouses"] = [(r.id(s), r.v(s, LM.code), r.v(s, LM.name), r.v(s, LM.address), r.wkt(s), r.v(s, LM.isActive),
                          r.v(s, LM.pincode), r.v(s, LM.service_radius_m)) for s in r.of(LM.Warehouse)]
    out["warehouse_staff"] = [(r.id(s), r.ref(s, LM.staffOf)) for s in users if g.value(s, LM.staffOf)]
    out["vehicles"] = [(r.id(s), r.local(s, LM.vehicleType), r.v(s, LM.registration_number), r.v(s, LM.max_weight_kg),
                        r.v(s, LM.max_volume_m3), r.v(s, LM.isActive)) for s in r.of(LM.Vehicle)]
    out["drivers"] = [(r.id(s), r.ref(s, LM.vehicle), r.v(s, LM.driverStatus), r.ref(s, LM.warehouse),
                       r.v(s, LM.shift_start), r.v(s, LM.shift_end)) for s in r.of(LM.Driver)]
    orders = []
    for s in r.of(LM.Order):
        win = g.value(s, LM.window)
        w0 = r.v(g.value(win, TIME.hasBeginning), TIME.inXSDDateTimeStamp) if win else None
        w1 = r.v(g.value(win, TIME.hasEnd), TIME.inXSDDateTimeStamp) if win else None
        orders.append((r.id(s), r.ref(s, LM.merchant), r.v(s, LM.merchant_order_ref), r.ref(s, LM.warehouse),
                       r.ref(s, LM.customer), r.local(s, LM.status), r.v(s, LM.recipient_name), r.v(s, LM.recipient_phone),
                       r.v(s, LM.delivery_address), r.wkt(s, LM.deliveryLocation), w0, w1, r.v(s, LM.weight_kg),
                       r.v(s, LM.volume_m3), r.v(s, LM.tracking_token), r.v(s, LM.pincode), r.v(s, LM.locality),
                       r.v(s, LM.landmark), r.v(s, LM.digipin), r.v(s, LM.payment_mode), r.v(s, LM.cod_amount_inr),
                       r.v(s, LM.planned_service_time_s), r.v(s, LM.created_at), r.v(s, LM.updated_at) or r.v(s, LM.created_at)))
    out["orders"] = orders
    out["routes"] = [(r.id(s), r.ref(s, LM.warehouse), r.ref(s, LM.driver), r.ref(s, LM.vehicle),
                      r.local(s, LM.status).replace("route_", ""), r.v(s, LM.total_distance_m), r.v(s, LM.total_duration_s),
                      r.v(s, LM.started_at), r.v(s, LM.completed_at), r.v(s, LM.created_at)) for s in r.of(LM.Route)]
    out["route_stops"] = [(r.id(s), r.ref(s, LM.route), r.ref(s, LM.order), int(r.v(s, LM.sequence)),
                           r.local(s, LM.status).replace("stop_", ""), r.local(s, LM.failureReason),
                           r.wkt(s, LM.plannedLocation), r.v(s, LM.planned_arrival_at), r.v(s, LM.arrived_at),
                           r.v(s, LM.completed_at)) for s in r.of(LM.RouteStop)]
    out["order_events"] = [(r.ref(s, LM.order), r.local(s, LM.fromStatus), r.local(s, LM.toStatus), r.v(s, LM.occurred_at))
                           for s in r.of(LM.OrderStatusChange)]
    attempts = r.of(LM.DeliveryAttempt)
    out["delivery_attempts"] = [(r.id(s), r.ref(s, LM.order), r.ref(s, LM.routeStop), r.ref(s, LM.driver), r.v(s, LM.outcome),
                                 r.local(s, LM.failureReason), r.v(s, LM.client_event_id), r.v(s, LM.occurred_at)) for s in attempts]
    out["processed_events"] = [(r.v(s, LM.client_event_id),
                                "delivery.completed" if r.v(s, LM.outcome) == "delivered" else "delivery.failed",
                                r.v(s, LM.occurred_at)) for s in attempts]
    return out


SQL = {
    "users": "INSERT INTO users (id,email,phone,password_hash,full_name,is_active,failed_login_count,locked_until) VALUES ($1::uuid,$2,$3,$4,$5,$6,$7,$8::timestamptz)",
    "user_roles": "INSERT INTO user_roles (user_id,role) VALUES ($1::uuid,$2::user_role)",
    "merchants": "INSERT INTO merchants (id,name,contact_email,contact_phone,is_active) VALUES ($1::uuid,$2,$3,$4,$5)",
    "merchant_members": "INSERT INTO merchant_members (user_id,merchant_id) VALUES ($1::uuid,$2::uuid)",
    "warehouses": "INSERT INTO warehouses (id,code,name,address,location,is_active,pincode,service_radius_m) VALUES ($1::uuid,$2,$3,$4,ST_GeogFromText($5),$6,$7,$8)",
    "warehouse_staff": "INSERT INTO warehouse_staff (user_id,warehouse_id) VALUES ($1::uuid,$2::uuid)",
    "vehicles": "INSERT INTO vehicles (id,type,registration_number,max_weight_kg,max_volume_m3,is_active) VALUES ($1::uuid,$2::vehicle_type,$3,$4,$5,$6)",
    "drivers": "INSERT INTO drivers (user_id,vehicle_id,status,home_warehouse_id,shift_start,shift_end) VALUES ($1::uuid,$2::uuid,$3::driver_status,$4::uuid,$5::time,$6::time)",
    "orders": """INSERT INTO orders (id,merchant_id,merchant_order_ref,warehouse_id,customer_id,status,recipient_name,recipient_phone,
                 delivery_address,delivery_location,window_earliest,window_latest,weight_kg,volume_m3,tracking_token,pincode,locality,
                 landmark,digipin,payment_mode,cod_amount_inr,service_time_s,created_at,updated_at)
                 VALUES ($1::uuid,$2::uuid,$3,$4::uuid,$5::uuid,$6::order_status,$7,$8,$9,ST_GeogFromText($10),$11::timestamptz,$12::timestamptz,
                 $13,$14,$15,$16,$17,$18,$19,$20::payment_mode,$21,$22,$23::timestamptz,$24::timestamptz)""",
    "routes": "INSERT INTO routes (id,warehouse_id,driver_id,vehicle_id,status,total_distance_m,total_duration_s,started_at,completed_at,created_at) VALUES ($1::uuid,$2::uuid,$3::uuid,$4::uuid,$5::route_status,$6,$7,$8::timestamptz,$9::timestamptz,$10::timestamptz)",
    "route_stops": "INSERT INTO route_stops (id,route_id,order_id,sequence,status,failure_reason,planned_location,planned_arrival_at,arrived_at,completed_at) VALUES ($1::uuid,$2::uuid,$3::uuid,$4,$5::stop_status,$6::failure_reason,ST_GeogFromText($7),$8::timestamptz,$9::timestamptz,$10::timestamptz)",
    "order_events": "INSERT INTO order_events (order_id,from_status,to_status,occurred_at) VALUES ($1::uuid,$2::order_status,$3::order_status,$4::timestamptz)",
    "delivery_attempts": "INSERT INTO delivery_attempts (id,order_id,route_stop_id,driver_id,outcome,failure_reason,client_event_id,occurred_at) VALUES ($1::uuid,$2::uuid,$3::uuid,$4::uuid,$5::attempt_outcome,$6::failure_reason,$7::uuid,$8::timestamptz)",
    "processed_events": "INSERT INTO processed_events (event_id,event_type,processed_at) VALUES ($1::uuid,$2,$3::timestamptz)",
}
ORDER = ["users", "user_roles", "merchants", "merchant_members", "warehouses", "warehouse_staff", "vehicles", "drivers",
         "orders", "routes", "route_stops", "order_events", "delivery_attempts", "processed_events"]


async def load(url, data):
    conn = await asyncpg.connect(url)
    try:
        if await conn.fetchval("select count(*) from orders"):
            raise SystemExit("target database already has orders — refusing to load (use an empty database)")
        async with conn.transaction():
            for table in ORDER:
                t0 = time.time()
                # rdflib already returns native types (Decimal, datetime, time,
                # bool, int); only UUIDs/enums travel as text with explicit casts.
                await conn.executemany(SQL[table], data[table])
                print(f"{table:18} {len(data[table]):6} rows  {time.time() - t0:5.1f}s")
    finally:
        await conn.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("ttl")
    ap.add_argument("--url", required=True)
    args = ap.parse_args()
    t0 = time.time()
    g = Graph().parse(args.ttl)
    print(f"parsed {len(g):,} triples in {time.time() - t0:.0f}s")
    data = rows(g)
    asyncio.run(load(args.url, data))


if __name__ == "__main__":
    main()
