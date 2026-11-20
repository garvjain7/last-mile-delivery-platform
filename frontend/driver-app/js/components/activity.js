import { state, escapeHTML, formatCount } from "../state.js";
import { outboxTransaction } from "../storage.js";

export function activityView() {
    return `<section class="page-heading"><p class="eyebrow">YOUR DAY, IN ORDER</p><h1>Activity</h1><p>Local actions and sync status for this device.</p></section>
        <section class="activity-summary"><span class="activity-summary-icon">↻</span><div><strong>${formatCount(state.outboxCount, "event")} still on this device</strong><small>Events remain here until the server confirms commit or you review a rejection.</small></div><button class="button button-secondary button-small" data-action="sync">Sync now</button></section>
        <div class="section-heading"><div><p class="eyebrow">RECENT</p><h3>On this device</h3></div></div>
        <div id="activity-list" class="activity-list"><div class="loading-line">Loading activity…</div></div>
        <div class="notice notice-warm"><span>i</span><div><strong>About syncing</strong><p>Gateway acceptance means an event reached Redis, not that it is saved in the database. Events are removed only after Core API confirms the Routing Worker committed them. Each queued action is bound to its driver account.</p></div></div>`;
}

export async function loadActivity() {
    const list = document.getElementById("activity-list");
    if (!list) return;
    try {
        const allRecords = await outboxTransaction("readonly", (store) => store.getAll());
        const records = allRecords.filter((record) => (
            !state.driverUserId || record.driver_user_id === state.driverUserId
        ));
        records.sort((left, right) => new Date(right.timestamp) - new Date(left.timestamp));
        const rejectedCount = records.filter((record) => record.sync_status === "rejected").length;
        const rejectedNotice = rejectedCount
            ? `<div class="notice notice-warm" role="alert"><span>!</span><div><strong>${formatCount(rejectedCount, "event")} rejected by the server</strong><p>Review the reason shown with each rejected event. Rejected events are retained on this device.</p></div></div>`
            : "";
        list.innerHTML = `${rejectedNotice}${records.length ? records.map((record) => {
            const rejected = record.sync_status === "rejected";
            const awaitingCommit = record.sync_status === "awaiting_commit";
            const queueState = rejected
                ? "REJECTED BY SERVER"
                : awaitingCommit
                    ? "AWAITING SERVER COMMIT"
                    : "WAITING TO SYNC";
            return `<article class="activity-row" ${rejected ? 'role="alert"' : ""}>
                <span class="activity-icon">${record.attachment ? "▣" : "↗"}</span>
                <div><strong>${escapeHTML(activityLabel(record.event_type))}</strong><small>${escapeHTML(record.order_id || record.route_id || "Route action")} · ${new Date(record.timestamp).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}</small>${rejected ? `<small class="form-error">${escapeHTML(record.reject_reason || "The server rejected this event.")}</small>` : ""}</div>
                <span class="queue-state">${queueState}</span>
            </article>`;
        }).join("") : `<div class="empty-state empty-state-small"><span>✓</span><h3>All caught up</h3><p>Your local activity will appear here.</p></div>`}`;
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
