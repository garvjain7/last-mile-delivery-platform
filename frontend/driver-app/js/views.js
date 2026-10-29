import { appRoot, escapeHTML, state } from "./state.js";
import { brandMark } from "./components/brand.js";
import { topbar } from "./components/navigation.js";
import { todayView } from "./components/dashboard.js";
import { routeOpportunitiesView, routeView } from "./components/routes.js";
import { deliveriesView } from "./components/deliveries.js";
import { activityView, loadActivity } from "./components/activity.js";
import { earningsView } from "./components/earnings.js";
import { profileView } from "./components/profile.js";

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
    if (state.view === "session-required") {
        appRoot.innerHTML = `<main class="session-required">${brandMark("session-required-mark")}<p class="eyebrow">LASTMILE / DRIVER</p>
            <h1>Central driver session required</h1>
            <p>Your organization's Core API authentication manages driver access. Complete central sign-in, then check your session here.</p>
            ${state.sessionMessage ? `<p class="session-message" role="status">${escapeHTML(state.sessionMessage)}</p>` : ""}
            <button class="button button-primary" data-action="check-central-session">Check session again</button></main>`;
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
    appRoot.innerHTML = `${topbar()}${offlineBanner}<main class="main-content">${tabContent()}</main>
        <nav class="bottom-nav" aria-label="Main navigation">${tabs.map((tab) => `
            <button class="nav-item ${state.tab === tab.id || (tab.id === "Routes" && state.tab === "Route") ? "is-active" : ""}" data-tab="${tab.id}" ${state.tab === tab.id || (tab.id === "Routes" && state.tab === "Route") ? 'aria-current="page"' : ""}>
                <span class="nav-icon">${tab.icon}</span><span>${tab.label}</span>
                ${tab.id === "Profile" && state.outboxCount ? `<i class="nav-badge"></i>` : ""}
            </button>`).join("")}
        </nav>`;
    if (state.tab === "Activity") loadActivity();
}
