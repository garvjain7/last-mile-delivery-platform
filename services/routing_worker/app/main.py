# ISOLATED COMPUTE ENGINE — No HTTP endpoints, pure consumer loop
# Main entrypoint launching Routing Worker persistent consumer loops.

import asyncio
import logging

from services.routing_worker.app.consumers.orders_consumer import run_orders_consumer
from services.routing_worker.app.consumers.terminal_events_consumer import (
    run_terminal_events_consumer,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("routing-worker")

async def start_consumer():
    """
    Launch persistent consumer loops for orders_stream (OSRM/VROOM solve)
    and driver_events_stream terminal events.
    """
    logger.info("Starting Routing Worker persistent consumer loops...")
    await asyncio.gather(
        run_orders_consumer(),
        run_terminal_events_consumer(),
    )

async def main():
    """CLI-compatible wrapper for running the worker outside the unified app."""
    try:
        await start_consumer()
    except Exception as e:
        logger.error(f"Routing Worker consumer error: {e}")
        raise

if __name__ == "__main__":
    asyncio.run(main())
