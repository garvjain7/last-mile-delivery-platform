import { state, escapeHTML } from "../state.js";

function routeDirectionsUrl(route, stops = route.stops) {
    const orderedStops = [...stops].sort((left, right) => left.sequence - right.sequence);
    const parameters = new URLSearchParams({
        api: "1",
        travelmode: "driving"
    });
    if (route.pickup_address) parameters.set("origin", route.pickup_address);
    if (orderedStops.length) {
        parameters.set("destination", orderedStops[orderedStops.length - 1].address);
        if (orderedStops.length > 1) {
            parameters.set("waypoints", orderedStops.slice(0, -1).map((stop) => stop.address).join("|"));
        }
    }
    return `https://www.google.com/maps/dir/?${parameters.toString()}`;
}

function routeEmbedUrl(route, stops, apiKey) {
    const parameters = new URLSearchParams({
        key: apiKey,
        origin: route.pickup_address || route.pickup,
        destination: stops[stops.length - 1].address,
        mode: "driving"
    });
    if (stops.length > 1) {
        parameters.set("waypoints", stops.slice(0, -1).map((stop) => stop.address).join("|"));
    }
    return `https://www.google.com/maps/embed/v1/directions?${parameters.toString()}`;
}

export function routeMap(route) {
    const orderedStops = [...route.stops].sort((left, right) => left.sequence - right.sequence);
    const isMapSample = orderedStops.length > 0
        && orderedStops.every((stop) => stop.tracking_token?.startsWith("MAP-"));
    const isSynthetic = !isMapSample
        && [route.pickup_address, ...orderedStops.map((stop) => stop.address)]
            .some((address) => /demo only|synthetic|preview/i.test(address || ""));
    const directionsUrl = routeDirectionsUrl(route, orderedStops);
    const apiKey = state.settings.googleMapsEmbedKey?.trim();
    if (isSynthetic || !orderedStops.length) {
        return `<section class="route-map-section">
            <div class="section-heading"><div><p class="eyebrow">GOOGLE MAPS</p><h3>Route map</h3></div></div>
            <p class="map-message" role="status">${isSynthetic
                ? "Map navigation is disabled for this route because its addresses are synthetic. Use real assigned delivery addresses for directions."
                : "This route has no delivery stops to show on a map."}</p>
        </section>`;
    }
    return `<section class="route-map-section">
        <div class="section-heading"><div><p class="eyebrow">GOOGLE MAPS</p><h3>Route map</h3></div>
            <a class="text-button" href="${escapeHTML(directionsUrl)}" target="_blank" rel="noopener noreferrer">Open full route <span>↗</span></a>
        </div>
        ${isMapSample ? `<p class="map-message map-sample-warning">Sample map only: destinations are broad place-name searches, not recipient addresses. Confirm exact addresses before real deliveries.</p>` : ""}
        ${apiKey ? `<iframe class="route-map-frame"
            title="Google Maps directions for the assigned delivery route"
            src="${escapeHTML(routeEmbedUrl(route, orderedStops, apiKey))}"
            loading="lazy"
            referrerpolicy="strict-origin-when-cross-origin"
            allowfullscreen></iframe>`
            : `<div class="map-message">
                <p>Add a Google Maps Embed API key in Profile → Sync settings to show the map here.</p>
                <p>The key is stored on this device. Restrict it to your app’s website referrer and the Maps Embed API in Google Cloud.</p>
            </div>`}
    </section>`;
}

export function routeSummary(route, actionLabel = "View route") {
    const action = route.status === "in_progress" ? "go-route" : "view-route";
    return `
        <article class="opportunity-card">
            <div class="opportunity-top"><span class="route-tag">ASSIGNED ROUTE</span><span class="route-status-dot"></span></div>
            <div class="opportunity-title"><div><h3>${escapeHTML(route.title)}</h3><p>${escapeHTML(route.area)}</p></div><span class="route-arrow">↗</span></div>
            <div class="route-stats">
                <span><b>${route.stop_count}</b><small>stops</small></span>
                <span><b>${route.distance_km}</b><small>km</small></span>
                <span><b>${Math.floor(route.duration_min / 60)}h ${route.duration_min % 60}m</b><small>est. time</small></span>
            </div>
            <div class="route-card-footer"><span class="pickup-pin">⌖</span> Pickup at <strong>${escapeHTML(route.pickup)}</strong><button class="text-button" data-action="${action}" data-route="${escapeHTML(route.route_id)}">${actionLabel} <span>→</span></button></div>
        </article>`;
}

export function activeRouteView() {
    const route = state.route;
    const remaining = route.stops.filter((stop) => !state.completed.has(stop.order_id) && !state.failed.has(stop.order_id));
    const nextStop = remaining[0];
    const pickupCount = state.pickupScanned.size;
    const manifestComplete = pickupCount === route.stops.length;
    const deliveredCount = route.stops.filter((stop) => state.completed.has(stop.order_id) || stop.status === "delivered").length;
    const failedCount = route.stops.filter((stop) => state.failed.has(stop.order_id) || stop.status === "failed").length;
    const progressCount = deliveredCount + failedCount;
    const progressPercent = route.stops.length ? Math.round((progressCount / route.stops.length) * 100) : 0;
    const mapUrl = (address) => `https://www.google.com/maps/dir/?api=1&destination=${encodeURIComponent(address)}&travelmode=driving`;
    return `
        <section class="route-hero">
            <div class="route-hero-top"><span class="route-tag route-tag-light">ACTIVE DELIVERY</span><span class="live-pill"><i></i> IN PROGRESS</span></div>
            <h2>${escapeHTML(route.title)}<span> · ${escapeHTML(route.area)}</span></h2>
            <div class="route-hero-stats"><span>${route.stop_count} stops</span><i></i><span>${route.distance_km} km</span><i></i><span>~${Math.floor(route.duration_min / 60)}h ${route.duration_min % 60}m</span></div>
            <div class="route-progress-block">
                <div class="route-progress-label"><span>Route progress</span><strong>${progressCount} of ${route.stops.length} accounted for</strong></div>
                <div class="route-progress-track" role="progressbar" aria-label="Route stops delivered or failed" aria-valuemin="0" aria-valuemax="${route.stops.length}" aria-valuenow="${progressCount}"><span style="width:${progressPercent}%"></span></div>
                <div class="route-progress-legend"><span><i class="legend-delivered"></i>${deliveredCount} delivered</span><span><i class="legend-remaining"></i>${remaining.length} remaining</span>${failedCount ? `<span><i class="legend-failed"></i>${failedCount} issue${failedCount === 1 ? "" : "s"}</span>` : ""}</div>
            </div>
        </section>
        ${!state.pickedUp ? `
            <section class="pickup-card">
                <div class="section-kicker"><span class="step-index">01</span><span>START AT THE HUB</span></div>
                <h3>Scan parcels at pickup</h3>
                <p>Pickup at <strong>${escapeHTML(route.pickup)}</strong>. Scan every parcel barcode before confirming the handoff.</p>
                <div class="scan-progress" role="status"><strong>${pickupCount} of ${route.stops.length} parcels scanned</strong><span class="queue-state">${navigator.onLine ? "ONLINE CHECK" : "OFFLINE CHECK"}</span></div>
                <button class="button button-secondary button-wide" data-action="scan-pickup">Scan next parcel <span>⌖</span></button>
                <button class="button button-primary button-wide" data-action="confirm-pickup" ${manifestComplete ? "" : "disabled"}>Confirm pickup <span>→</span></button>
                <p class="field-hint">Scans are verified against your route manifest. Scan history is queued to Redis, not saved as a database record.</p>
            </section>` : `
            <section class="next-stop-card">
                <div class="next-stop-heading"><div><p class="eyebrow">NEXT DELIVERY · STOP ${remaining.length ? String(route.stop_count - remaining.length + 1).padStart(2, "0") : "—"}</p><h3>${nextStop ? escapeHTML(nextStop.recipient) : "Route complete"}</h3></div><span class="next-stop-number">${remaining.length ? String(route.stop_count - remaining.length + 1).padStart(2, "0") : "✓"}</span></div>
                ${nextStop ? `<p class="stop-address">${escapeHTML(nextStop.address)}</p>
                <div class="stop-contact">
                    ${nextStop.recipient_phone ? `<a class="button button-secondary stop-contact-action" href="tel:${escapeHTML(nextStop.recipient_phone)}"><span aria-hidden="true">☎</span> Call recipient</a>` : ""}
                    ${/demo only|synthetic|preview/i.test(nextStop.address) && !nextStop.tracking_token?.startsWith("MAP-")
                        ? `<span class="map-notice">Navigation unavailable for sample address</span>`
                        : `<a class="button button-primary stop-contact-action" href="${mapUrl(nextStop.address)}" target="_blank" rel="noopener noreferrer"><span aria-hidden="true">↗</span> Get directions</a>`}
                    ${nextStop.tracking_token?.startsWith("MAP-") ? `<span class="map-notice">Demo location only</span>` : ""}
                </div>
                <p class="stop-window"><span aria-hidden="true">◷</span><span>${escapeHTML(nextStop.window || "Delivery window unavailable")}</span></p>
                <div class="stop-actions">
                    ${!state.stopScanned.has(nextStop.order_id) ? `<button class="button button-secondary button-wide" data-action="scan-stop" data-order="${escapeHTML(nextStop.order_id)}">Scan parcel for this stop <span>⌖</span></button>` : ""}
                    ${state.stopScanned.has(nextStop.order_id) && !state.arrived.has(nextStop.order_id) ? `<button class="button button-primary button-wide" data-action="arrive-stop" data-order="${escapeHTML(nextStop.order_id)}">I'm at the stop · GPS check-in <span>→</span></button>` : ""}
                    ${state.arrived.has(nextStop.order_id) ? `<button class="button button-primary button-wide" data-action="open-delivery" data-order="${escapeHTML(nextStop.order_id)}">Complete delivery <span>→</span></button>` : ""}
                    <button class="button button-quiet" data-action="open-exception" data-order="${escapeHTML(nextStop.order_id)}">Report an issue</button>
                </div>` : `<p class="stop-address">Every stop is accounted for. Nice work out there.</p><button class="button button-primary" data-action="finish-route">Finish this route <span>→</span></button>`}
                <p class="field-hint">Arrival uses an explicit GPS check-in. No geofence radius is configured.</p>
            </section>`}
        <div class="route-display-toolbar">
            <div><p class="eyebrow">ROUTE DETAILS</p><h3>Map & stop feed</h3></div>
            <div class="route-display-switch" role="group" aria-label="Route display">
                <button type="button" data-route-panel="map" aria-pressed="${state.routePanel === "map"}" class="${state.routePanel === "map" ? "is-active" : ""}">Map</button>
                <button type="button" data-route-panel="feed" aria-pressed="${state.routePanel === "feed"}" class="${state.routePanel === "feed" ? "is-active" : ""}">Stop feed</button>
            </div>
        </div>
        ${state.routePanel === "map" ? routeMap(route) : `<section class="section-block stop-list-section" aria-label="Route stop feed">
            <div class="section-heading"><div><p class="eyebrow">YOUR MANIFEST</p><h3>Delivery stops</h3></div><span class="count-pill">${route.stops.length} shown</span></div>
            <ol class="stop-list">${route.stops.map((stop, index) => {
                const done = state.completed.has(stop.order_id);
                const failed = state.failed.has(stop.order_id);
                const active = nextStop?.order_id === stop.order_id;
                return `<li class="stop-row ${done ? "is-done" : ""} ${failed ? "is-failed" : ""} ${active ? "is-next" : ""}">
                    <span class="stop-marker">${done ? "✓" : failed ? "!" : String(index + 1).padStart(2, "0")}</span>
                    <div class="stop-info"><strong>${escapeHTML(stop.recipient)}</strong><span>${escapeHTML(stop.address)}</span><small>${escapeHTML(stop.window)}</small>${stop.recipient_phone ? `<a href="tel:${escapeHTML(stop.recipient_phone)}">Call ${escapeHTML(stop.recipient_phone)}</a>` : ""}</div>
                    <span class="stop-result">${done ? "Delivered" : failed ? "Exception" : active ? "Next up" : "Queued"}</span>
                </li>`;
            }).join("")}</ol>
        </section>`}`;
}

export function routeOpportunitiesView() {
    const availableRoutes = state.driverRoutes.filter((route) => route.status === "planned");
    return `
        <section class="page-heading"><p class="eyebrow">YOUR ASSIGNED WORK</p><h1>Planned routes</h1><p>Review routes assigned to your driver account and start an eligible route.</p></section>
        ${state.route ? `<section class="active-callout"><span class="callout-icon">✓</span><div><strong>You have an active route</strong><small>Finish or return your current parcels before taking another.</small></div><button class="text-button" data-tab="Route">View <span>→</span></button></section>` : ""}
        <div class="board-meta"><span>ASSIGNED PLANNED ROUTES</span><span>From your account</span></div>
        ${availableRoutes.length
            ? `<div class="opportunity-list">${availableRoutes.map((route) => routeSummary(route, "Review")).join("")}</div>`
            : `<div class="empty-state"><span>↗</span><h3>No planned routes yet</h3><p>Routes assigned to your driver profile will appear here.</p></div>`}
        <p class="field-hint">Only routes assigned to your driver account are shown here.</p>`;
}

export function routeView() {
    if (!state.route) {
        return `<section class="page-heading"><p class="eyebrow">YOUR MANIFEST</p><h1>No active route</h1><p>Your assigned route details will appear here after you start a planned route.</p></section>
            <div class="empty-state"><span>↗</span><h3>No active route</h3><p>Review a planned route assigned to your account to get started.</p><button class="button button-primary" data-tab="Routes">View planned routes <span>→</span></button></div>`;
    }
    return activeRouteView();
}
