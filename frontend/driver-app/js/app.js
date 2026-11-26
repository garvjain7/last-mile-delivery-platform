import { state, appRoot, escapeHTML, notify } from "./state.js";
import { openDatabase, restoreWorkState, refreshOutboxCount, removeLegacyDemoData, clearWorkState } from "./storage.js";
import { apiRequest } from "./api.js";
import { render } from "./views.js";
import { syncOutbox, acceptRoute, confirmPickup, scanPickupParcel, scanStopParcel, arriveAtStop, openDelivery, openException, openRouteDetails, startLocation, startDemoLocationSimulation, stopLocationTracking, stopDemoLocationSimulation } from "./services/driver-events.js";
import {
    addPaymentMethod,
    finishRoute,
    loadDriverAccount,
    refreshFinancialData,
    saveDriverProfile,
    searchVehicles,
    selectPreferredPaymentMethod
} from "./services/account.js";
import { dismissCustomerNoteUpdate, openCustomerChat, receiveCustomerNoteUpdate } from "./components/communications.js";
import { showOrderRequest } from "./components/order-request.js";
import { showSosConfirmation } from "./components/safety-tools.js";

document.addEventListener("driver:render", render);

async function restoreCentralSession() {
    let identity;
    try {
        identity = await apiRequest("/auth/me");
    } catch (error) {
        stopLocationTracking();
        stopDemoLocationSimulation();
        console.warn("Could not verify the centralized driver session.", error);
        state.sessionIssue = error?.status === 401
            ? "authentication"
            : !navigator.onLine || error?.name === "TypeError"
                ? "connection"
                : "verification";
        state.sessionMessage = state.sessionIssue === "authentication"
            ? "Sign in through your organization's centralized authentication, then check your session again."
            : state.sessionIssue === "connection"
                ? "Connect to the network to verify your centralized driver session."
                : "The authentication service could not verify your session. Try again shortly.";
        state.view = "session-required";
        render();
        return;
    }
    if (!identity.roles?.includes("driver")) {
        stopLocationTracking();
        stopDemoLocationSimulation();
        state.sessionIssue = "role";
        state.sessionMessage = "The active Core API session does not have the driver role.";
        state.view = "session-required";
        render();
        return;
    }
    try {
        await loadDriverAccount(identity);
    } catch (error) {
        stopLocationTracking();
        stopDemoLocationSimulation();
        console.error("Could not load the driver account.", error);
        state.sessionIssue = "account";
        state.sessionMessage = !navigator.onLine
            ? "Connect to the network, then retry loading your driver account."
            : `Your session is valid, but driver data could not be loaded: ${error?.message || "Please try again."}`;
        state.view = "session-required";
        render();
        return;
    }
    state.sessionIssue = "";
    state.sessionMessage = "";
    state.view = "app";
    render();
    try {
        await syncOutbox({ quiet: true });
    } catch (error) {
        console.warn("Could not synchronize the driver outbox after session restore.", error);
        notify("Your session is active, but saved driver actions could not be synchronized.", "warning");
    }
}

function clearDriverSessionState() {
    stopLocationTracking();
    stopDemoLocationSimulation();
    state.identity = null;
    state.driverUserId = null;
    state.route = null;
    state.driverRoutes = [];
    state.customerNoteUpdates = {};
    state.pickedUp = false;
    state.pickupScanned = new Set();
    state.stopScanned = new Set();
    state.completed = new Set();
    state.failed = new Set();
    state.arrived = new Set();
    state.location = null;
    state.demoLocation = null;
    state.demoProgress = null;
    state.locationMode = "off";
    state.locationStatus = "Location not shared";
    state.outboxCount = 0;
    state.rejectedOutboxCount = 0;
    state.isSyncing = false;
    state.syncRequested = false;
    state.driverProfile = null;
    state.earnings = null;
    state.earningsError = "";
    state.financialDataLoading = false;
    state.paymentMethods = [];
    state.paymentMethodsError = "";
    state.tab = "Today";
    state.view = "session-required";
    state.sessionIssue = "authentication";
    state.sessionMessage = "You are signed out. Sign in with your central account to continue.";
    attemptCookieCleanup();
}

function attemptCookieCleanup() {
    try {
        document.cookie.split(";").forEach((cookie) => {
            const [name] = cookie.split("=");
            if (!name) return;
            document.cookie = `${name.trim()}=; expires=Thu, 01 Jan 1970 00:00:00 GMT; path=/; SameSite=Lax`;
        });
    } catch (error) {
        console.warn("Could not clear browser cookies during logout.", error);
    }
}

async function logoutDriverSession() {
    try {
        await apiRequest("/auth/logout", { method: "POST", body: "{}" });
    } catch (error) {
        console.warn("Central logout request failed. Clearing local driver session anyway.", error);
        notify("Your local driver session was cleared. Please sign in again.", "warning");
    } finally {
        await clearWorkState();
        clearDriverSessionState();
        render();
        window.location.assign("http://127.0.0.1:8000/login");
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
        if (state.tab === "Earnings") await refreshFinancialData();
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
    if (action === "open-central-login") window.location.assign("http://127.0.0.1:8000/login");
    if (action === "logout-driver-app") await logoutDriverSession();
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
    if (action === "open-customer-chat") openCustomerChat(button.dataset.order);
    if (action === "dismiss-customer-note") dismissCustomerNoteUpdate(button.dataset.order);
    if (action === "confirm-sos") showSosConfirmation();
    if (action === "sync") {
        await syncOutbox();
        await refreshFinancialData();
    }
    if (action === "refresh-financial-data") await refreshFinancialData();
    if (action === "start-location") await startLocation();
    if (action === "demo-gps") startDemoLocationSimulation();
    if (action === "search-vehicles") await searchVehicles();
    if (action === "save-driver-profile") await saveDriverProfile();
    if (action === "open-payment-method-modal") {
        document.getElementById("payment-method-dialog")?.showModal();
    }
    if (action === "add-payment-method") await addPaymentMethod();
    if (action === "select-payment-method") {
        await selectPreferredPaymentMethod(button.dataset.paymentMethod);
    }
    if (action === "close-dialog") button.closest("dialog")?.close();
});

window.addEventListener("driver:customer-note-updated", (event) => {
    receiveCustomerNoteUpdate(event.detail);
});

window.addEventListener("driver:order-request", (event) => {
    showOrderRequest(event.detail);
});

document.addEventListener("input", (event) => {
    const slider = event.target.closest("[data-route-start]");
    if (!slider) return;
    slider.setAttribute(
        "aria-valuetext",
        slider.value === "100" ? "Ready to start" : `${slider.value} percent`
    );
    const hint = slider.parentElement.querySelector("[data-route-start-hint]");
    if (hint) hint.textContent = slider.value === "100"
        ? "Release to start the assigned route."
        : "Slide to the end to start · keyboard-accessible";
});

document.addEventListener("change", async (event) => {
    const paymentTypeSelect = event.target.closest("#payment-method-type");
    if (paymentTypeSelect) {
        document.querySelectorAll("[data-payment-fields]").forEach((fields) => {
            fields.hidden = fields.dataset.paymentFields !== paymentTypeSelect.value;
        });
        return;
    }
    const slider = event.target.closest("[data-route-start]");
    if (!slider || slider.value !== "100") return;
    slider.closest("dialog")?.close();
    await acceptRoute(slider.dataset.routeStart);
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

if (navigator.connection?.addEventListener) {
    navigator.connection.addEventListener("change", () => {
        if (state.view === "app") render();
    });
}

startApp();
