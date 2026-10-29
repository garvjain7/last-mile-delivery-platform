

export const appRoot = document.getElementById("app-content");

export const toastRegion = document.getElementById("toast-region");

export const state = {
    db: null,
    view: "session-required",
    tab: "Today",
    deliveriesFilter: "All",
    routePanel: "map",
    sessionMessage: "",
    identity: null,
    driverUserId: null,
    route: null,
    pickedUp: false,
    pickupScanned: new Set(),
    stopScanned: new Set(),
    completed: new Set(),
    failed: new Set(),
    arrived: new Set(),
    location: null,
    locationStatus: "Location not shared",
    outboxCount: 0,
    isSyncing: false,
    syncRequested: false,
    settings: readSettings(),
    driverProfile: null,
    driverRoutes: [],
    vehicles: []
};

export function readSettings() {
    try {
        return JSON.parse(localStorage.getItem("driver.settings") || "{}");
    } catch (error) {
        console.error("Could not read saved driver settings.", error);
        return {};
    }
}

export function saveSettings() {
    localStorage.setItem("driver.settings", JSON.stringify(state.settings));
}

export function escapeHTML(value) {
    return String(value ?? "").replace(/[&<>"']/g, (character) => ({
        "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
    })[character]);
}

export function formatCount(value, singular, plural = `${singular}s`) {
    return `${value} ${value === 1 ? singular : plural}`;
}

export function notify(message, type = "info") {
    const toast = document.createElement("div");
    toast.className = `toast toast-${type}`;
    toast.textContent = message;
    toastRegion.append(toast);
    window.setTimeout(() => toast.remove(), 3600);
}

export function showError(message) {
    const error = document.getElementById("screen-error");
    if (error) {
        error.textContent = message;
        error.hidden = false;
    } else {
        notify(message, "error");
    }
}
