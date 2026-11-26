import asyncio

from streaming import client
from streaming.schemas.events import RoutePublishedEvent


class FakeRedis:
    def __init__(self):
        self.add_arguments = None

    async def xadd(self, stream_name, fields, **kwargs):
        self.add_arguments = (stream_name, fields, kwargs)
        return "1-0"


def test_add_to_stream_encodes_nested_values_and_omits_nulls(monkeypatch):
    redis_client = FakeRedis()

    async def get_redis_client():
        return redis_client

    monkeypatch.setattr(client, "get_redis_client", get_redis_client)

    result = asyncio.run(
        client.add_to_stream(
            "route_stream",
            {
                "event_id": "event-1",
                "enabled": False,
                "stops": [{"order_id": "order-1"}],
                "optional": None,
            },
        )
    )

    assert result == "1-0"
    assert redis_client.add_arguments == (
        "route_stream",
        {
            "event_id": "event-1",
            "enabled": "false",
            "stops": '[{"order_id":"order-1"}]',
        },
        {"maxlen": 50_000, "approximate": True},
    )


def test_route_published_event_decodes_json_stops_from_stream():
    event = RoutePublishedEvent.model_validate(
        {
            "event_id": "event-1",
            "route_id": "route-1",
            "vehicle_id": "vehicle-1",
            "driver_id": "driver-1",
            "driver_name": "Driver",
            "vehicle_registration": "KA 01 AB 1234",
            "stops": '[{"order_id":"order-1"}]',
            "created_at": "2026-11-18T08:00:00+00:00",
        }
    )

    assert event.stops == [{"order_id": "order-1"}]
