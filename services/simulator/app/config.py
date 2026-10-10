# Configuration settings loader for World Simulator.
# Loads external API endpoint URLs for simulation runner.

import os
from dotenv import load_dotenv
from pydantic import BaseModel

load_dotenv()

class SimulatorConfig(BaseModel):
    """Configuration properties for synthetic traffic simulator."""
    core_api_url: str = os.getenv("CORE_API_URL", "http://localhost:8000")
    driver_gateway_url: str = os.getenv("DRIVER_GATEWAY_URL", "http://localhost:8000/driver")
    num_virtual_drivers: int = int(os.getenv("NUM_VIRTUAL_DRIVERS", "5"))
    order_generation_rate_sec: int = int(os.getenv("ORDER_GENERATION_RATE_SEC", "10"))

config = SimulatorConfig()
