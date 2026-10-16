// Pure EventSource / WebSocket connection layers
// Connects to Control Tower WebSocket feed for targeted live DOM updates.

class ControlTowerApp {
    constructor() {
        this.ws = null;
        this.drivers = new Map();
    }

    init() {
        console.log("Initializing Control Tower WebSocket connection...");
        // TODO: Connect to WebSocket endpoint ws://localhost:8001/ws/fleet
        // TODO: Perform targeted DOM/marker updates on driver delta receive
    }

    triggerRescue(vehicleId) {
        // TODO: Send POST request to /rescue/{vehicle_id} endpoint
    }
}

document.addEventListener("DOMContentLoaded", () => {
    const app = new ControlTowerApp();
    app.init();
});
