import { state, notify, saveSettings } from "../state.js";
import { clearWorkState, persistWorkState } from "../storage.js";
import { apiRequest, normalizeDriverRoute } from "../api.js";
import { render } from "../views.js";
import { syncOutbox } from "./driver-events.js";

export async function loadDriverAccount(identity) {
    const [profile, routes, vehicles] = await Promise.all([
        apiRequest("/driver/profile"),
        apiRequest("/driver/routes"),
        apiRequest("/driver/vehicles")
    ]);
    state.identity = {
        ...identity,
        user_id: profile.user_id,
        full_name: profile.full_name,
        phone: profile.phone,
        driver_status: profile.status
    };
    state.driverUserId = profile.user_id;
    state.driverProfile = profile;
    state.driverRoutes = routes.map(normalizeDriverRoute);
    state.vehicles = vehicles;
    const serverRoute = state.driverRoutes.find((route) => route.status === "in_progress") || null;
    const savedRoute = state.route;
    state.route = serverRoute;
    if (serverRoute) {
        state.pickedUp = savedRoute?.route_id === serverRoute.route_id && state.pickedUp;
        if (savedRoute?.route_id !== serverRoute.route_id) {
            state.pickupScanned = new Set();
            state.stopScanned = new Set();
            state.completed = new Set(serverRoute.stops.filter((stop) => stop.status === "delivered").map((stop) => stop.order_id));
            state.failed = new Set(serverRoute.stops.filter((stop) => stop.status === "failed").map((stop) => stop.order_id));
            state.arrived = new Set();
        }
        await persistWorkState();
    } else {
        state.pickedUp = false;
        state.pickupScanned = new Set();
        state.stopScanned = new Set();
        state.completed = new Set();
        state.failed = new Set();
        state.arrived = new Set();
        await clearWorkState();
    }
}

export async function searchVehicles() {
    const search = document.getElementById("vehicle-search")?.value.trim() || "";
    try {
        state.vehicles = await apiRequest(
            `/driver/vehicles${search ? `?search=${encodeURIComponent(search)}` : ""}`
        );
        render();
        notify(search ? "Vehicle search updated." : "Available vehicles refreshed.", "success");
    } catch (error) {
        notify(error.message || "Could not search available vehicles.", "error");
    }
}

export async function finishRoute() {
    if (!state.route) return;
    if (state.outboxCount) await syncOutbox({ quiet: true });
    if (state.outboxCount) {
        notify("Route updates are still waiting to sync. Keep the route open until they are accepted.", "error");
        return;
    }
    try {
        const routes = await apiRequest("/driver/routes");
        if (routes.some((route) => route.route_id === state.route.route_id)) {
            notify("The delivery updates are still being processed. Try again shortly.", "info");
            return;
        }
        state.driverProfile.status = "available";
    } catch (error) {
        notify(`Could not confirm route completion: ${error.message}`, "error");
        return;
    }
    state.route = null;
    state.pickedUp = false;
    state.pickupScanned = new Set();
    state.stopScanned = new Set();
    state.completed = new Set();
    state.failed = new Set();
    state.arrived = new Set();
    await clearWorkState();
    state.tab = "Today";
    render();
    notify("Route completion confirmed.", "success");
}

export async function saveProfileSettings() {
    const gatewayUrl = document.getElementById("gateway-api-url")?.value.trim();
    const googleMapsEmbedKey = document.getElementById("google-maps-embed-key")?.value.trim();
    const vehicle = document.getElementById("vehicle-registration")?.value || "";
    try {
        const fullName = document.getElementById("driver-full-name")?.value.trim();
        const phone = document.getElementById("driver-phone")?.value.trim();
        const profileChanges = {};
        if (fullName && fullName !== state.identity.full_name) profileChanges.full_name = fullName;
        if (phone && phone !== state.identity.phone) profileChanges.phone = phone;
        if (Object.keys(profileChanges).length) {
            state.driverProfile = await apiRequest("/driver/profile", {
                method: "PATCH",
                body: JSON.stringify(profileChanges)
            });
            state.identity.full_name = state.driverProfile.full_name;
            state.identity.phone = state.driverProfile.phone;
        }

        if (vehicle && vehicle !== state.driverProfile.vehicle?.vehicle_id) {
            state.driverProfile = await apiRequest("/driver/vehicle", {
                method: "PUT",
                body: JSON.stringify({ vehicle_id: vehicle })
            });
            state.vehicles = await apiRequest("/driver/vehicles");
        }

        if (gatewayUrl) state.settings.driverGatewayBase = gatewayUrl.replace(/\/+$/, "");
        if (googleMapsEmbedKey) {
            state.settings.googleMapsEmbedKey = googleMapsEmbedKey;
        } else {
            delete state.settings.googleMapsEmbedKey;
        }
        saveSettings();
        render();
        notify("Profile settings saved.", "success");
    } catch (error) {
        notify(error.message || "Could not save profile settings.", "error");
    }
}
