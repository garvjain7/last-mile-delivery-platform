# Isolated VROOM / OSRM matrix compilation and HTTP clients
# HTTP client for interacting with self-hosted OSRM routing engine.

import httpx
from typing import List, Tuple, Dict, Any
from app.config import config

class OSRMClient:
    """HTTP client for OSRM table and route APIs with explicit timeouts."""

    def __init__(self):
        self.base_url = config.osrm_url
        self.timeout = httpx.Timeout(connect=3.0, read=10.0, write=5.0, pool=5.0)

    async def get_table_matrix(self, coordinates: List[Tuple[float, float]]) -> Dict[str, Any]:
        """
        Query OSRM table API for travel time/distance duration matrix.
        
        # TODO: Send httpx GET request to OSRM table endpoint with coordinates
        """
        # TODO: Implement OSRM table matrix request
        return {"durations": [], "distances": []}
