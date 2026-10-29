import { state, escapeHTML, formatCount } from "../state.js";
import { outboxTransaction } from "../storage.js";

export function activityView() {
    return `<section class="page-heading"><p class="eyebrow">YOUR DAY, IN ORDER</p><h1>Activity</h1><p>Local actions and sync status for this device.</p></section>
        <section class="activity-summary"><span class="activity-summary-icon">↻</span><div><strong>${formatCount(state.outboxCount, "item")} waiting to sync</strong><small>Saved to the offline queue first.</small></div><button class="button button-secondary button-small" data-action="sync">Sync now</button></section>
        <div class="section-heading"><div><p class="eyebrow">RECENT</p><h3>On this device</h3></div></div>
        <div id="activity-list" class="activity-list"><div class="loading-line">Loading activity…</div></div>
        <div class="notice notice-warm"><span>i</span><div><strong>About syncing</strong><p>Queued events replay in order using your central driver session. Each queued action is bound to its driver account and will not be sent under another driver's session.</p></div></div>`;
}

export async function loadActivity() {
    const list = document.getElementById("activity-list");
    if (!list) return;
    try {
        const records = await outboxTransaction("readonly", (store) => store.getAll());
        records.sort((left, right) => new Date(right.timestamp) - new Date(left.timestamp));
        list.innerHTML = records.length ? records.map((record) => `
            <article class="activity-row">
                <span class="activity-icon">${record.attachment ? "▣" : "↗"}</span>
                <div><strong>${escapeHTML(activityLabel(record.event_type))}</strong><small>${escapeHTML(record.order_id || record.route_id || "Route action")} · ${new Date(record.timestamp).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}</small></div>
                <span class="queue-state">WAITING TO SYNC</span>
            </article>`).join("") : `<div class="empty-state empty-state-small"><span>✓</span><h3>All caught up</h3><p>Your local activity will appear here.</p></div>`;
    } catch (error) {
        console.error("Could not load activity.", error);
        list.innerHTML = `<p class="form-error">Could not load local activity. ${escapeHTML(error.message)}</p>`;
    }
}

export function activityLabel(eventType) {
    return ({
        "route.started": "Route started",
        "stop.arrived": "Arrived at delivery stop",
        "delivery.completed": "Delivery completed",
        "delivery.failed": "Delivery exception recorded",
        "driver.location.updated": "Location check-in",
        "package.scanned": "Parcel scanned",
        "pickup.confirmed": "Pickup confirmed",
        "pod.captured": "Proof of delivery captured",
        "delivery.exception.evidence": "Exception photo captured"
    })[eventType] || "Driver activity";
}
