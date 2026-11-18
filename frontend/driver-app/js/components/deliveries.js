import { state, escapeHTML } from "../state.js";

const filters = ["All", "Pending", "Scanned", "Arrived", "Delivered", "Failed", "Skipped"];

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
        return { label: "Arrived", key: "Arrived", className: "is-arrived" };
    }
    if (state.stopScanned.has(stop.order_id)) {
        return { label: "Scanned", key: "Scanned", className: "is-scanned" };
    }
    return { label: "Pending", key: "Pending", className: "is-pending" };
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
    const activeFilter = filters.includes(state.deliveriesFilter) ? state.deliveriesFilter : "All";
    const visibleStops = stops.filter((stop) => {
        if (activeFilter === "All") return true;
        return stopStatus(stop).key === activeFilter;
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
                    <div><strong>${statuses.filter((status) => status.key === "Pending" || status.key === "Scanned" || status.key === "Arrived").length}</strong><span>Remaining</span></div>
                </div>
            </section>
            <section class="delivery-manifest" aria-label="Current route delivery manifest">
                <div class="delivery-filter-heading"><div><p class="eyebrow">CURRENT ROUTE</p><h2>Stop manifest</h2></div><span class="count-pill">${stops.length} stops</span></div>
                <div class="delivery-filters" role="group" aria-label="Filter route stops">
                    ${filters.map((filter) => `<button class="delivery-filter ${activeFilter === filter ? "is-active" : ""}" data-delivery-filter="${filter}" aria-pressed="${activeFilter === filter}">${filter}</button>`).join("")}
                </div>
            <div class="delivery-history-list">
                ${visibleStops.length
                    ? visibleStops.map((stop) => deliveryRow(stop, stops.indexOf(stop))).join("")
                    : `<div class="empty-state empty-state-small"><span>✓</span><h3>No ${activeFilter.toLowerCase()} deliveries</h3><p>Try another filter to see the route manifest.</p></div>`}
            </div>
            </section>
        ` : `
            <div class="empty-state delivery-empty"><span>▤</span><h3>No active delivery manifest</h3><p>Assigned route stops will appear here when a route is in progress.</p><button class="button button-primary" data-tab="Routes">View routes <span>→</span></button></div>
        `}
        <button class="profile-link-card" data-tab="Earnings"><span class="activity-summary-icon">₹</span><span><strong>Earnings &amp; wallet</strong><small>View available balance and transactions</small></span><b>→</b></button>
        <button class="profile-link-card" data-tab="Activity"><span class="activity-summary-icon">↻</span><span><strong>Offline activity & sync</strong><small>${state.outboxCount ? `${state.outboxCount} item${state.outboxCount === 1 ? "" : "s"} waiting to sync` : "View pending device activity"}</small></span><b>→</b></button>`;
}
