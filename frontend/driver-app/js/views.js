import { appRoot, escapeHTML, state } from "./state.js";
import { brandMark } from "./components/brand.js";
import { topbar } from "./components/navigation.js";
import { todayView } from "./components/dashboard.js";
import { routeOpportunitiesView, routeStickyAction, routeView } from "./components/routes.js";
import { deliveriesView } from "./components/deliveries.js";
import { activityView, loadActivity } from "./components/activity.js";
import { earningsView } from "./components/earnings.js";
import { profileView } from "./components/profile.js";
import { closeCustomerChatIfInactive } from "./components/communications.js";
import { closeSosConfirmationIfInactive, sosButton } from "./components/safety-tools.js";

export function tabContent() {
    if (state.tab === "Today") return todayView();
    if (state.tab === "Routes") return routeOpportunitiesView();
    if (state.tab === "Route") return routeView();
    if (state.tab === "Deliveries") return deliveriesView();
    if (state.tab === "Earnings") return earningsView();
    if (state.tab === "Activity") return activityView();
    return profileView();
}

export function render() {
    if (!state.db) return;
    closeCustomerChatIfInactive(state.view !== "app");
    closeSosConfirmationIfInactive();
    if (state.view === "session-required") {
        const accountUnavailable = state.sessionIssue === "account";
        const accessRequired = state.sessionIssue === "role";
        const heading = accountUnavailable
            ? "Driver account unavailable"
            : accessRequired
                ? "Driver access required"
                : state.sessionIssue === "verification" || state.sessionIssue === "connection"
                    ? "Couldn't verify driver session"
                    : "Central driver session required";
        const description = accountUnavailable
            ? "Your central session is active, but driver profile and route data could not be loaded."
            : accessRequired
                ? "The signed-in account does not have the driver role. Contact your organization administrator."
                : state.sessionIssue === "connection"
                    ? "Reconnect to the network to verify your existing session and load driver information."
                    : state.sessionIssue === "verification"
                        ? "The central authentication service could not verify your session. Try again shortly."
                        : "Use the organization sign-in page to authenticate, then return to this app to continue your route.";
        appRoot.innerHTML = `<main class="session-required">${brandMark("session-required-mark")}<p class="eyebrow">LASTMILE / DRIVER</p>
            <h1>${heading}</h1>
            <p>${description}</p>
            ${state.sessionMessage ? `<p class="session-message" role="status">${escapeHTML(state.sessionMessage)}</p>` : ""}
            <div class="session-actions">
                <button class="button button-primary" data-action="check-central-session">${accountUnavailable ? "Retry driver data" : "Check session again"}</button>
                <button class="button button-secondary" data-action="open-central-login">Open central sign in</button>
                <button class="button button-secondary" data-action="logout-driver-app">Log out</button>
            </div></main>`;
        return;
    }
    const offlineBanner = !navigator.onLine
        ? `<div class="offline-banner" role="status"><span class="offline-banner-icon">!</span><div><strong>You're offline</strong><p>Driver actions are saved to this device and will sync when you're connected.</p></div><span class="offline-queue-count">${state.outboxCount} queued</span></div>`
        : "";
    const tabs = [
        { id: "Today", label: "Home", icon: "⌂" },
        { id: "Routes", label: "Routes", icon: "↗" },
        { id: "Deliveries", label: "Deliveries", icon: "▤" },
        { id: "Profile", label: "Profile", icon: "○" }
    ];
    const stickyRouteAction = state.tab === "Route" ? routeStickyAction() : "";
    const emergencyAction = state.tab === "Route" ? sosButton() : "";
    appRoot.innerHTML = `${topbar()}${offlineBanner}<main class="main-content ${stickyRouteAction ? "has-sticky-action" : ""}">${tabContent()}</main>${stickyRouteAction}${emergencyAction}
        <nav class="bottom-nav" aria-label="Primary navigation">${tabs.map((tab) => `
            <button class="nav-item ${state.tab === tab.id || (tab.id === "Routes" && state.tab === "Route") ? "is-active" : ""}" data-tab="${tab.id}" aria-label="${tab.label}" ${state.tab === tab.id || (tab.id === "Routes" && state.tab === "Route") ? 'aria-current="page"' : ""}>
                <span class="nav-icon" aria-hidden="true">${tab.icon}</span><span>${tab.label}</span>
                ${tab.id === "Profile" && state.outboxCount ? `<i class="nav-badge" aria-label="${state.outboxCount} queued items"></i>` : ""}
            </button>`).join("")}
        </nav>`;
    if (state.tab === "Activity") loadActivity();
}
