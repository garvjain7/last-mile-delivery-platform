import asyncio
from uuid import uuid4

from services.routing_worker.app.consumers import orders_consumer


class FakeRedis:
    def __init__(self):
        self.acknowledgements = []

    async def xack(self, stream_name, group_name, message_id):
        self.acknowledgements.append((stream_name, group_name, message_id))


def test_order_event_publishes_to_route_stream_before_acknowledgement(monkeypatch):
    order_id = uuid4()
    warehouse_id = uuid4()
    route_event = {"route_id": str(uuid4())}
    published = []

    async def plan_routes(_warehouse_id, _order_id):
        return True, [route_event]

    async def publish(stream_name, event):
        published.append((stream_name, event))

    monkeypatch.setattr(orders_consumer, "plan_warehouse_routes", plan_routes)
    monkeypatch.setattr(orders_consumer, "add_to_stream", publish)
    redis_client = FakeRedis()

    asyncio.run(
        orders_consumer._process_message(
            redis_client,
            "1-0",
            {
                "event_id": str(uuid4()),
                "order_id": str(order_id),
                "merchant_id": str(uuid4()),
                "warehouse_id": str(warehouse_id),
                "dropoff_location": "POINT(77.5 12.9)",
                "dropoff_raw_address": "Delivery address",
                "time_window": "",
                "weight_kg": "1.25",
                "volume_m3": "0.5",
                "created_at": "2026-11-18T08:00:00+00:00",
            },
        )
    )

    assert published == [("route_stream", route_event)]
    assert redis_client.acknowledgements == [
        ("orders_stream", "routing-workers", "1-0")
    ]
