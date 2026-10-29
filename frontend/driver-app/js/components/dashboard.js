import { state, escapeHTML } from "../state.js";
import { greeting } from "./navigation.js";
import { routeSummary } from "./routes.js";

export function todayView() {
    const openStops = state.route ? state.route.stops.filter((stop) => !state.completed.has(stop.order_id) && !state.failed.has(stop.order_id)).length : 0;
    const completedStops = state.route ? state.completed.size : 0;
    const failedStops = state.route ? state.failed.size : 0;
    const totalStops = state.route?.stops.length || 0;
    const progressPercent = totalStops
        ? Math.round(((completedStops + failedStops) / totalStops) * 100)
        : 0;
    const availableRoutes = state.driverRoutes.filter((route) => route.status === "planned");
    return `
        <section class="welcome-row"><div><p class="eyebrow">${new Date().toLocaleDateString(undefined, { weekday: "long", month: "long", day: "numeric" }).toUpperCase()}</p><h1>${greeting()}</h1></div><span class="weather-mark" aria-label="Ready for the day">✳</span></section>
        ${!state.identity?.driver_status ? `<div class="notice notice-warm"><span>!</span><div><strong>Driver profile is not linked yet</strong><p>Route and vehicle details are unavailable for this account.</p></div></div>` : ""}
        <section class="shift-card">
            <div class="shift-copy"><span class="shift-icon">↗</span><div><p class="eyebrow">DRIVER STATUS</p><h2>${state.route ? "Route in progress" : "No active route"}</h2></div></div>
            <p>${state.route ? `${openStops} stops left on your active route.` : "Review routes assigned to your driver account."}</p>
            <div class="shift-bottom">
                <span class="shift-state"><i></i>${state.route ? "ROUTE ACTIVE" : "ACCOUNT STATUS"}</span>
                <span>${state.identity?.driver_status ? escapeHTML(state.identity.driver_status.replaceAll("_", " ").toUpperCase()) : "PROFILE STATUS N/A"}</span>
                ${state.driverProfile?.vehicle?.registration_number
                    ? `<span>VEHICLE · ${escapeHTML(state.driverProfile.vehicle.registration_number)}</span>`
                    : ""}
            </div>
        </section>
        ${state.route ? `<section class="daily-progress" aria-label="Today's delivery progress">
            <div class="daily-progress-heading"><div><p class="eyebrow">TODAY'S ROUTE</p><h2>Delivery progress</h2></div><strong>${progressPercent}%</strong></div>
            <div class="progress-track" role="progressbar" aria-label="Route stops completed or reported" aria-valuemin="0" aria-valuemax="${totalStops}" aria-valuenow="${completedStops + failedStops}">
                <span style="width:${progressPercent}%"></span>
            </div>
            <div class="progress-stats">
                <div><strong>${completedStops}</strong><span>Delivered</span></div>
                <div><strong>${totalStops}</strong><span>Daily stops</span></div>
                <div><strong>${failedStops}</strong><span>Issues</span></div>
            </div>
        </section>` : ""}
        ${state.route ? `<section class="next-action-card">
            <div class="next-action-icon">${state.pickedUp ? "⌖" : "▦"}</div>
            <div class="next-action-copy"><p class="eyebrow">NEXT ACTION</p><strong>${nextActionLabel()}</strong><small>${nextActionDetail()}</small></div>
            <button class="button button-primary button-small" data-tab="Route">Open <span>→</span></button>
        </section>` : ""}
        ${state.route ? `<div class="section-heading"><div><p class="eyebrow">PICK UP WHERE YOU LEFT OFF</p><h3>Active route</h3></div><button class="text-button" data-tab="Route">Open route <span>→</span></button></div>
            ${routeSummary(state.route, "Continue")}
            <div class="home-quick-actions"><button data-action="start-location"><span>⌖</span><strong>Share location</strong><small>GPS check-in</small></button><button data-action="sync"><span>↻</span><strong>Sync activity</strong><small>${state.outboxCount} waiting</small></button></div>
        ` : `
            <div class="section-heading"><div><p class="eyebrow">YOUR ASSIGNED WORK</p><h3>Planned routes</h3></div><span class="count-pill">${availableRoutes.length} assigned</span></div>
            ${availableRoutes.length
                ? `<div class="opportunity-list">${availableRoutes.map((route) => routeSummary(route, "Review")).join("")}</div>`
                : `<div class="empty-state empty-state-small"><span>↗</span><h3>No planned routes</h3><p>Routes assigned to your driver profile will appear here.</p></div>`}
        `}
        <section class="location-strip">
            <span class="location-icon">⌖</span><div><strong>Location services</strong><small>${escapeHTML(state.locationStatus)}</small></div><button class="text-button" data-action="start-location">${state.location ? "Refresh" : "Enable"} <span>→</span></button>
        </section>
        <section class="home-earnings-preview">
            <div><p class="eyebrow">EARNINGS PREVIEW</p><strong>Payout data unavailable</strong><small>${completedStops} delivered ${completedStops === 1 ? "stop" : "stops"} · amount not provided</small></div>
            <button class="text-button" data-tab="Earnings">Details <span>→</span></button>
        </section>`;
}

function nextActionLabel() {
    if (!state.pickedUp) return "Scan parcels at pickup";
    const nextStop = state.route.stops.find((stop) => (
        !state.completed.has(stop.order_id) && !state.failed.has(stop.order_id)
    ));
    if (!nextStop) return "Finish your route";
    if (!state.stopScanned.has(nextStop.order_id)) return `Scan parcel · ${nextStop.recipient}`;
    if (!state.arrived.has(nextStop.order_id)) return `Confirm arrival · ${nextStop.recipient}`;
    return `Complete delivery · ${nextStop.recipient}`;
}

function nextActionDetail() {
    if (!state.pickedUp) return `${state.route.pickup} · scan the manifest before confirming pickup`;
    const nextStop = state.route.stops.find((stop) => (
        !state.completed.has(stop.order_id) && !state.failed.has(stop.order_id)
    ));
    if (!nextStop) return "All route stops are accounted for";
    return nextStop.address;
}
