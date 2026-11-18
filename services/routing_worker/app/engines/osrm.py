# Isolated VROOM / OSRM matrix compilation and HTTP clients
# HTTP client for interacting with self-hosted OSRM routing engine.

import httpx
import math
from typing import List, Tuple, Dict, Any
from services.routing_worker.app.config import config

class OSRMClient:
    """HTTP client for OSRM table and route APIs with explicit timeouts."""

    def __init__(self):
        self.base_url = config.osrm_url
        self.timeout = httpx.Timeout(connect=3.0, read=10.0, write=5.0, pool=5.0)

    async def get_table_matrix(self, coordinates: List[Tuple[float, float]]) -> Dict[str, Any]:
        """Return OSRM travel-time and distance matrices for [longitude, latitude] points."""
        if not coordinates:
            raise ValueError("At least one coordinate is required.")
        coordinate_path = ";".join(f"{longitude},{latitude}" for longitude, latitude in coordinates)
        url = f"{self.base_url.rstrip('/')}/table/v1/driving/{coordinate_path}"
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.get(
                url,
                params={"annotations": "duration,distance"},
            )
            response.raise_for_status()
            try:
                body = response.json()
            except ValueError as exc:
                raise RuntimeError("OSRM returned invalid JSON for its table response.") from exc

        if not isinstance(body, dict):
            raise RuntimeError("OSRM returned an invalid table response.")
        durations = body.get("durations")
        distances = body.get("distances")
        expected_size = len(coordinates)
        if body.get("code") != "Ok" or not _valid_matrix(durations, expected_size) or not _valid_matrix(distances, expected_size):
            raise RuntimeError("OSRM did not return complete duration and distance matrices.")
        return {
            "durations": [[int(math.ceil(value)) for value in row] for row in durations],
            "distances": [[int(math.ceil(value)) for value in row] for row in distances],
        }

    async def get_route_distance(self, start: Tuple[float, float], end: Tuple[float, float]) -> int:
        """Return the routed distance in meters between two [longitude, latitude] points."""
        coordinate_path = f"{start[0]},{start[1]};{end[0]},{end[1]}"
        url = f"{self.base_url.rstrip('/')}/route/v1/driving/{coordinate_path}"
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.get(url, params={"overview": "false", "steps": "false"})
            response.raise_for_status()
            try:
                body = response.json()
            except ValueError as exc:
                raise RuntimeError("OSRM returned invalid JSON for its route response.") from exc
        routes = body.get("routes") if isinstance(body, dict) else None
        if body.get("code") != "Ok" or not isinstance(routes, list) or not routes:
            raise RuntimeError("OSRM did not return a route between the requested points.")
        distance = routes[0].get("distance")
        if not isinstance(distance, (int, float)) or not math.isfinite(distance) or distance < 0:
            raise RuntimeError("OSRM returned an invalid route distance.")
        return int(math.ceil(distance))


def _valid_matrix(matrix: Any, expected_size: int) -> bool:
    return (
        isinstance(matrix, list)
        and len(matrix) == expected_size
        and all(
            isinstance(row, list)
            and len(row) == expected_size
            and all(
                isinstance(value, (int, float)) and math.isfinite(value) and value >= 0
                for value in row
            )
            for row in matrix
        )
    )
