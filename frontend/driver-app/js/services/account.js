import { state, notify } from "../state.js";
import { clearWorkState, persistWorkState } from "../storage.js";
import {
    apiRequest,
    createPaymentMethod,
    getDriverEarnings,
    getPaymentMethods,
    normalizeDriverRoute,
    setPreferredPaymentMethod
} from "../api.js";
import { render } from "../views.js";
import { syncOutbox, stopLocationTracking, stopDemoLocationSimulation } from "./driver-events.js";
import { isPickupConfirmedForRoute } from "./route-state.mjs";

let activeFinancialRequests = 0;

function financialLoadError(error, resource) {
    if (error?.status === 404) {
        return `${resource} aren't available from the active service yet.`;
    }
    if (error?.status >= 500) {
        return `${resource} couldn't be loaded because the service encountered an error. Try again shortly.`;
    }
    if (error?.name === "TypeError") {
        return `Couldn't connect to ${resource.toLowerCase()}. Check your connection and try again.`;
    }
    return error?.message || `${resource} couldn't be loaded.`;
}

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
    await refreshFinancialData(false);
    const serverRoute = state.driverRoutes.find((route) => route.status === "in_progress") || null;
    const savedRoute = state.route;
    if (savedRoute?.route_id !== serverRoute?.route_id) {
        stopLocationTracking();
        stopDemoLocationSimulation();
    }
    state.route = serverRoute;
    if (serverRoute) {
        state.pickedUp = isPickupConfirmedForRoute(serverRoute, savedRoute);
        if (savedRoute?.route_id !== serverRoute.route_id) {
            state.customerNoteUpdates = {};
            state.pickupScanned = new Set();
            state.stopScanned = new Set();
            state.arrived = new Set();
        }
        state.completed = new Set([
            ...state.completed,
            ...serverRoute.stops.filter((stop) => stop.status === "delivered").map((stop) => stop.order_id)
        ]);
        state.failed = new Set([
            ...state.failed,
            ...serverRoute.stops.filter((stop) => stop.status === "failed").map((stop) => stop.order_id)
        ]);
        await persistWorkState();
    } else {
        state.customerNoteUpdates = {};
        state.pickedUp = false;
        state.pickupScanned = new Set();
        state.stopScanned = new Set();
        state.completed = new Set();
        state.failed = new Set();
        state.arrived = new Set();
        await clearWorkState();
    }
}

export async function refreshFinancialData(renderAfter = true) {
    activeFinancialRequests += 1;
    state.financialDataLoading = true;
    state.earningsError = "";
    state.paymentMethodsError = "";
    if (renderAfter) render();
    try {
        const [earningsResult, paymentMethodsResult] = await Promise.allSettled([
            getDriverEarnings(),
            getPaymentMethods()
        ]);
        state.earnings = earningsResult.status === "fulfilled" ? earningsResult.value : null;
        state.earningsError = earningsResult.status === "rejected"
            ? financialLoadError(earningsResult.reason, "Earnings data")
            : "";
        state.paymentMethods = paymentMethodsResult.status === "fulfilled"
            ? paymentMethodsResult.value
            : [];
        state.paymentMethodsError = paymentMethodsResult.status === "rejected"
            ? financialLoadError(paymentMethodsResult.reason, "Payout methods")
            : "";
    } finally {
        activeFinancialRequests -= 1;
        state.financialDataLoading = activeFinancialRequests > 0;
        if (renderAfter) render();
    }
}

export async function addPaymentMethod() {
    const methodType = document.getElementById("payment-method-type")?.value;
    const payload = { method_type: methodType };
    if (methodType === "upi") {
        payload.upi_id = document.getElementById("payment-upi-id")?.value.trim();
    } else {
        payload.account_holder_name = document.getElementById("payment-account-holder")?.value.trim();
        payload.account_number = document.getElementById("payment-account-number")?.value.trim();
        payload.ifsc_code = document.getElementById("payment-ifsc")?.value.trim();
    }
    payload.is_preferred = state.paymentMethods.length === 0;
    try {
        await createPaymentMethod(payload);
        await refreshFinancialData(false);
        render();
        notify("Payout method saved securely.", "success");
    } catch (error) {
        notify(error.message || "Could not save payout method.", "error");
    }
}

export async function selectPreferredPaymentMethod(methodId) {
    try {
        await setPreferredPaymentMethod(methodId);
        await refreshFinancialData(false);
        render();
        notify("Preferred payout method updated.", "success");
    } catch (error) {
        notify(error.message || "Could not update preferred payout method.", "error");
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
    stopLocationTracking();
    stopDemoLocationSimulation();
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

export async function saveDriverProfile() {
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

        render();
        notify("Profile changes saved.", "success");
    } catch (error) {
        notify(error.message || "Could not save profile settings.", "error");
    }
}
