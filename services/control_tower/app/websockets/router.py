# High-speed Uvicorn/WebSocket broadcast router to dispatch views
# WebSocket router and rescue trigger endpoint for Control Tower dashboard.

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, status
from typing import List

router = APIRouter()

class ConnectionManager:
    """Manages active WebSocket connections for live fleet dashboard broadcasting."""

    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, message: dict):
        for connection in self.active_connections:
            await connection.send_json(message)

manager = ConnectionManager()

@router.websocket("/ws/fleet")
async def fleet_websocket_endpoint(websocket: WebSocket):
    """WebSocket endpoint pushing targeted live driver/order state updates to Control Tower UI."""
    await manager.connect(websocket)
    try:
        while True:
            # TODO: Receive client ping or keepalive
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)

@router.post("/rescue/{vehicle_id}")
async def trigger_rescue(vehicle_id: str):
    """Trigger dynamic rescue re-route for an affected vehicle's remaining stops."""
    # TODO: Publish rescue trigger event for Routing Worker to re-solve affected vehicle stops
    return {"vehicle_id": vehicle_id, "status": "rescue_triggered"}
