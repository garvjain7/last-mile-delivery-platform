import { state, appRoot, escapeHTML, notify } from "./state.js";
import { openDatabase, restoreWorkState, refreshOutboxCount, removeLegacyDemoData } from "./storage.js";
import { apiRequest } from "./api.js";
import { render } from "./views.js";
import { syncOutbox, acceptRoute, confirmPickup, scanPickupParcel, scanStopParcel, arriveAtStop, openDelivery, openException, openRouteDetails, startLocation } from "./services/driver-events.js";
import { loadDriverAccount, searchVehicles, finishRoute, saveProfileSettings } from "./services/account.js";

async function restoreCentralSession() {
    try {
        const identity = await apiRequest("/auth/me");
        if (!identity.roles?.includes("driver")) {
            state.sessionMessage = "The active Core API session does not have the driver role.";
            state.view = "session-required";
            render();
            return;
        }
        await loadDriverAccount(identity);
        state.sessionMessage = "";
        state.view = "app";
        render();
        await syncOutbox({ quiet: true });
    } catch (error) {
        console.warn("Could not restore the centralized driver session.", error);
        state.sessionMessage = navigator.onLine
            ? "Sign in through your organization's centralized authentication, then check your session again."
            : "Connect to the network to verify your centralized driver session.";
        state.view = "session-required";
        render();
    }
}

async function startApp() {
    try {
        state.db = await openDatabase();
        await removeLegacyDemoData();
        if ("serviceWorker" in navigator) {
            navigator.serviceWorker.register("/driver-app-sw.js", { scope: "/" }).catch((error) => {
                console.error("Could not register the offline app shell.", error);
                notify("Offline app shell could not be installed.", "error");
            });
        }
        await restoreWorkState();
        await refreshOutboxCount();
        await restoreCentralSession();
    } catch (error) {
        console.error("Driver app initialization failed.", error);
        appRoot.innerHTML = `<main class="fatal-state"><div class="brand-mark">F<span>·</span></div><h1>Couldn't prepare offline storage</h1><p>${escapeHTML(error.message)}</p><button class="button button-primary" onclick="window.location.reload()">Try again</button></main>`;
    }
}

document.addEventListener("click", async (event) => {
    const deliveryFilter = event.target.closest("[data-delivery-filter]");
    if (deliveryFilter) {
        state.deliveriesFilter = deliveryFilter.dataset.deliveryFilter;
        render();
        return;
    }
    const tabButton = event.target.closest("[data-tab]");
    if (tabButton) {
        state.tab = tabButton.dataset.tab;
        render();
        return;
    }
    const routePanelButton = event.target.closest("[data-route-panel]");
    if (routePanelButton) {
        state.routePanel = routePanelButton.dataset.routePanel;
        render();
        return;
    }
    const button = event.target.closest("[data-action]");
    if (!button) return;
    const { action } = button.dataset;
    if (action === "check-central-session") await restoreCentralSession();
    if (action === "finish-route") await finishRoute();
    if (action === "go-home") { event.preventDefault(); state.tab = "Today"; render(); }
    if (action === "go-route") { state.tab = "Route"; render(); }
    if (action === "view-route") openRouteDetails(button.dataset.route);
    if (action === "accept-route") {
        button.closest("dialog")?.close();
        await acceptRoute(button.dataset.route);
    }
    if (action === "arrive-stop") await arriveAtStop(button.dataset.order);
    if (action === "scan-pickup") await scanPickupParcel();
    if (action === "confirm-pickup") await confirmPickup();
    if (action === "scan-stop") await scanStopParcel(button.dataset.order);
    if (action === "open-delivery") openDelivery(button.dataset.order);
    if (action === "open-exception") openException(button.dataset.order);
    if (action === "sync") await syncOutbox();
    if (action === "start-location") await startLocation();
    if (action === "search-vehicles") await searchVehicles();
    if (action === "save-profile-settings") saveProfileSettings();
    if (action === "close-dialog") button.closest("dialog")?.close();
});

window.addEventListener("online", async () => {
    if (state.view === "app") {
        notify("Connection restored.", "success");
        render();
        await syncOutbox({ quiet: true });
    }
});

window.addEventListener("offline", () => {
    if (state.view === "app") {
        notify("You're offline. Actions are being saved on this device.", "error");
        render();
    }
});

startApp();
