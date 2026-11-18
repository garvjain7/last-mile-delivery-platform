# Isolated VROOM / OSRM matrix compilation and HTTP clients
# HTTP client for interacting with self-hosted VROOM optimization engine.

import math
import httpx
from typing import Dict, Any
from services.routing_worker.app.config import config

class VROOMClient:
    """HTTP client for VROOM CVRPTW solver with explicit timeouts."""

    def __init__(self):
        self.base_url = config.vroom_url
        self.timeout = httpx.Timeout(connect=3.0, read=15.0, write=5.0, pool=5.0)

    async def solve_cvrptw(self, problem_payload: Dict[str, Any]) -> Dict[str, Any]:
        """Solve the supplied vehicle-routing problem through the configured VROOM API."""
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(self.base_url.rstrip("/"), json=problem_payload)
            response.raise_for_status()
            try:
                body = response.json()
            except ValueError as exc:
                raise RuntimeError("VROOM returned invalid JSON.") from exc
        return parse_vroom_solution(body)

def parse_vroom_solution(response_json: Dict[str, Any]) -> Dict[str, Any]:
    """Validate the VROOM response shape consumed by route persistence."""
    if not isinstance(response_json, dict):
        raise RuntimeError("VROOM returned an invalid response.")
    if response_json.get("code") != 0:
        raise RuntimeError(f"VROOM could not solve the route: {response_json.get('error', 'unknown error')}")
    routes = response_json.get("routes")
    unassigned = response_json.get("unassigned", [])
    if not isinstance(routes, list) or not isinstance(unassigned, list):
        raise RuntimeError("VROOM returned an invalid solution shape.")
    for route in routes:
        if not isinstance(route, dict) or not isinstance(route.get("steps"), list):
            raise RuntimeError("VROOM returned a route without steps.")
        for step in route["steps"]:
            if not isinstance(step, dict):
                raise RuntimeError("VROOM returned an invalid route step.")
            if "arrival" in step and (
                not isinstance(step["arrival"], (int, float))
                or not math.isfinite(step["arrival"])
            ):
                raise RuntimeError("VROOM returned an invalid step arrival.")
            if "distance" in step and (
                not isinstance(step["distance"], (int, float))
                or not math.isfinite(step["distance"])
                or step["distance"] < 0
            ):
                raise RuntimeError("VROOM returned an invalid step distance.")
    return response_json
