import { state, escapeHTML } from "../state.js";

const filters = ["All", "Open", "Delivered", "Failed", "Skipped"];

function stopStatus(stop) {
    if (state.completed.has(stop.order_id) || stop.status === "delivered") {
        return { label: "Delivered", key: "Delivered", className: "is-done" };
    }
    if (state.failed.has(stop.order_id) || stop.status === "failed") {
        return { label: "Failed", key: "Failed", className: "is-failed" };
    }
    if (stop.status === "skipped") {
        return { label: "Skipped", key: "Skipped", className: "is-skipped" };
    }
    if (state.arrived.has(stop.order_id)) {
        return { label: "Arrived", key: "Open", className: "is-arrived" };
    }
    if (state.stopScanned.has(stop.order_id)) {
        return { label: "Scanned", key: "Open", className: "is-scanned" };
    }
    return { label: "Pending", key: "Open", className: "is-pending" };
}

function deliveryRow(stop, index) {
    const status = stopStatus(stop);
    return `<article class="delivery-history-row ${status.className}">
        <span class="delivery-history-index">${String(index + 1).padStart(2, "0")}</span>
        <div class="delivery-history-details">
            <strong>${escapeHTML(stop.recipient || `Stop ${index + 1}`)}</strong>
            <span>${escapeHTML(stop.address)}</span>
            <small>${escapeHTML(stop.window || "Delivery window unavailable")}${stop.tracking_token ? ` · ${escapeHTML(stop.tracking_token)}` : ""}</small>
        </div>
        <span class="delivery-status">${status.label}</span>
    </article>`;
}

export function deliveriesView() {
    const stops = state.route
        ? [...state.route.stops].sort((left, right) => left.sequence - right.sequence)
        : [];
    const statuses = stops.map((stop) => stopStatus(stop));
    const delivered = statuses.filter((status) => status.key === "Delivered").length;
    const failed = statuses.filter((status) => status.key === "Failed").length;
    const open = statuses.filter((status) => status.key === "Open").length;
    const activeFilter = state.deliveriesFilter || "All";
    const visibleStops = stops.filter((stop) => {
        if (activeFilter === "All") return true;
        return stopStatus(stop).key === activeFilter;
    });
    const filterOptions = filters.filter((filter) => {
        if (filter === "Open") return open > 0 || activeFilter === "Open";
        if (filter === "Skipped") return statuses.some((status) => status.key === "Skipped") || activeFilter === "Skipped";
        return true;
    });
    return `
        <section class="page-heading">
            <p class="eyebrow">DRIVER MANIFEST</p>
            <h1>Deliveries</h1>
            <p>${state.route ? `${escapeHTML(state.route.title)} · current assigned route` : "Current route stops and delivery outcomes."}</p>
        </section>
        ${state.route ? `
            <section class="delivery-summary-card">
                <div class="delivery-summary-heading"><div><p class="eyebrow">ROUTE PROGRESS</p><h2>${escapeHTML(state.route.title)}</h2></div><button class="text-button" data-tab="Route">Open route <span>→</span></button></div>
                <div class="delivery-summary-stats">
                    <div><strong>${stops.length}</strong><span>Total stops</span></div>
                    <div><strong>${delivered}</strong><span>Delivered</span></div>
                    <div><strong>${failed}</strong><span>Failed</span></div>
                    <div><strong>${open}</strong><span>Open</span></div>
                </div>
            </section>
            <div class="delivery-filters" aria-label="Filter deliveries">
                ${filterOptions.map((filter) => `<button class="delivery-filter ${activeFilter === filter ? "is-active" : ""}" data-delivery-filter="${filter}" aria-pressed="${activeFilter === filter}">${filter}</button>`).join("")}
            </div>
            <div class="delivery-history-list">
                ${visibleStops.length
                    ? visibleStops.map((stop) => deliveryRow(stop, stops.indexOf(stop))).join("")
                    : `<div class="empty-state empty-state-small"><span>✓</span><h3>No ${activeFilter.toLowerCase()} deliveries</h3><p>Try another filter to see the route manifest.</p></div>`}
            </div>
        ` : `
            <div class="empty-state delivery-empty"><span>▤</span><h3>No active delivery manifest</h3><p>Assigned route stops will appear here when a route is in progress.</p><button class="button button-primary" data-tab="Routes">View routes <span>→</span></button></div>
        `}
        <section class="notice notice-warm delivery-history-note">
            <span>i</span><div><strong>Past delivery history</strong><p>The driver API currently returns planned and in-progress routes only. Historical completed, failed, or returned orders are not available here.</p></div>
        </section>
        <button class="profile-link-card" data-tab="Earnings"><span class="activity-summary-icon">₹</span><span><strong>Earnings & payouts</strong><small>Payout data is not connected to the driver API</small></span><b>→</b></button>
        <button class="profile-link-card" data-tab="Activity"><span class="activity-summary-icon">↻</span><span><strong>Offline activity & sync</strong><small>${state.outboxCount ? `${state.outboxCount} item${state.outboxCount === 1 ? "" : "s"} waiting to sync` : "View pending device activity"}</small></span><b>→</b></button>`;
}
