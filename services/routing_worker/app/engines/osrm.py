# Isolated VROOM / OSRM matrix compilation and HTTP clients
# HTTP client for interacting with self-hosted OSRM routing engine.

import httpx
from typing import List, Tuple, Dict, Any
from app.config import config

class OSRMClient:
    """HTTP client for OSRM table and route APIs with explicit timeouts."""

    def __init__(self):
        self.base_url = config.osrm_url
        self.timeout = httpx.Timeout(
            connect=config.osrm_connect_timeout,
            read=config.osrm_read_timeout,
            write=config.osrm_write_timeout,
            pool=config.osrm_connect_timeout
        )

    async def get_table_matrix(self, coordinates: List[Tuple[float, float]]) -> Dict[str, Any]:
        """
        Query OSRM table API for travel time/distance duration matrix.
        
        # TODO: Send httpx GET request to OSRM table endpoint with coordinates
        """
        # TODO: Implement OSRM table matrix request
        return {"durations": [], "distances": []}
