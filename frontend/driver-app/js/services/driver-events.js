import { state, escapeHTML, formatCount, notify } from "../state.js";
import {
    enqueueOutboxRecord,
    outboxTransaction,
    persistWorkState,
    refreshOutboxCount
} from "../storage.js";
import { apiBase, apiRequest, normalizeDriverRoute } from "../api.js";
import { render } from "../views.js";
import { routeMap } from "../components/routes.js";
import { scanBarcode } from "../components/scanner.js";
import { captureException, captureProofOfDelivery } from "../components/pod.js";

export function eventLocation() {
    return state.location ? { latitude: state.location.latitude, longitude: state.location.longitude } : null;
}

export async function queueEvent(eventType, details = {}, attachment = null) {
    const event_id = crypto.randomUUID();
    const timestamp = new Date().toISOString();
    const record = {
        event_id,
        event_type: eventType,
        timestamp,
        driver_user_id: state.driverUserId,
        ...details,
        ...(attachment ? { attachment } : {})
    };
    await enqueueOutboxRecord(record);
    state.outboxCount += 1;
    render();
    if (navigator.onLine) {
        void syncOutbox({ quiet: true }).catch((error) => {
            console.error("Automatic driver event sync failed.", error);
            notify("An event could not be synced. It remains in the offline queue.", "error");
        });
    }
    return record;
}

export function getLocation() {
    if (!("geolocation" in navigator)) {
        return Promise.reject(new Error("This device does not support location services."));
    }
    state.locationStatus = "Getting a GPS fix…";
    render();
    return new Promise((resolve, reject) => {
        navigator.geolocation.getCurrentPosition((position) => {
            state.location = {
                latitude: position.coords.latitude,
                longitude: position.coords.longitude,
                accuracy: position.coords.accuracy,
                timestamp: new Date(position.timestamp).toISOString()
            };
            state.locationStatus = `GPS ready · ±${Math.round(position.coords.accuracy)} m`;
            resolve(state.location);
        }, (error) => {
            state.locationStatus = "Location permission needed";
            const messages = {
                1: "Allow location access to record a GPS check-in.",
                2: "GPS could not determine your location. Try again outdoors.",
                3: "GPS request timed out. Try again."
            };
            reject(new Error(messages[error.code] || "Unable to access location."));
        }, { enableHighAccuracy: true, timeout: 12000, maximumAge: 30000 });
    });
}

export async function recordTelemetry(eventType, details = {}, attachment = null) {
    const location = eventLocation();
    if (!location) throw new Error("Get a GPS fix before recording this action.");
    return queueEvent(eventType, {
        latitude: location.latitude,
        longitude: location.longitude,
        current_route_id: state.route?.route_id || null,
        ...details
    }, attachment);
}

export async function syncOutbox({ quiet = false } = {}) {
    if (state.isSyncing) {
        state.syncRequested = true;
        return;
    }
    if (!navigator.onLine) {
        if (!quiet) notify("You're offline. Actions will sync when you're connected.", "error");
        return;
    }
    if (!state.driverUserId) {
        if (!quiet) notify("A central driver session is required to sync queued events.", "error");
        return;
    }
    let synced = 0;
    let firstError = "";
    let heldForOtherAccount = false;
    let syncAgain = false;
    state.isSyncing = true;
    try {
        const identity = await apiRequest("/auth/me");
        if (identity.user_id !== state.driverUserId || !identity.roles?.includes("driver")) {
            throw new Error("The active session does not match this driver's queued actions.");
        }
        let records = await outboxTransaction("readonly", (store) => store.getAll());
        while (true) {
            heldForOtherAccount = heldForOtherAccount || records.some((record) => (
                record.driver_user_id !== state.driverUserId
            ));
            const pending = records
                .filter((record) => record.driver_user_id === state.driverUserId)
                .sort((left, right) => {
                    const leftSequence = Number.isInteger(left.queue_sequence) ? left.queue_sequence : null;
                    const rightSequence = Number.isInteger(right.queue_sequence) ? right.queue_sequence : null;
                    if (leftSequence !== null && rightSequence !== null) return leftSequence - rightSequence;
                    const timestampDifference = Date.parse(left.timestamp) - Date.parse(right.timestamp);
                    if (Number.isFinite(timestampDifference) && timestampDifference !== 0) return timestampDifference;
                    return (leftSequence || 0) - (rightSequence || 0)
                        || String(left.event_id).localeCompare(String(right.event_id));
                });
            const record = pending[0];
            if (!record) break;
            try {
                const payload = {
                    event_id: record.event_id,
                    driver_id: record.driver_user_id,
                    event_type: record.event_type,
                    timestamp: record.timestamp
                };
                if (record.event_type === "route.started") {
                    payload.route_id = record.route_id;
                } else if (record.event_type === "package.scanned") {
                    payload.route_id = record.route_id;
                    payload.order_id = record.order_id;
                    payload.tracking_token = record.tracking_token;
                    payload.scan_stage = record.scan_stage;
                } else if (record.event_type === "pickup.confirmed") {
                    payload.route_id = record.route_id;
                    payload.scanned_order_ids = record.scanned_order_ids;
                } else {
                    payload.latitude = record.latitude;
                    payload.longitude = record.longitude;
                    if (record.current_route_id) payload.current_route_id = record.current_route_id;
                    if (record.order_id) payload.order_id = record.order_id;
                    if (record.failure_reason) payload.failure_reason = record.failure_reason;
                    if (record.failure_notes) payload.failure_notes = record.failure_notes;
                    if (record.return_to_hub) payload.return_to_hub = true;
                }
                let requestUrl = `${apiBase()}/driver/events`;
                let requestOptions = {
                    method: "POST",
                    credentials: "include",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify(payload)
                };
                if (["pod.captured", "delivery.exception.evidence"].includes(record.event_type)) {
                    if (!record.attachment) {
                        firstError = "Evidence attachment is missing; the queued record was retained.";
                        break;
                    }
                    const form = new FormData();
                    form.set("event_id", record.event_id);
                    form.set("route_id", record.route_id);
                    form.set("order_id", record.order_id);
                    form.set("evidence_type", record.attachment.evidenceType);
                    form.set("purpose", record.purpose);
                    if (record.attachment.recipientName) {
                        form.set("recipient_name", record.attachment.recipientName);
                    }
                    if (record.attachment.file) {
                        const extension = record.attachment.evidenceType === "signature" ? "png" : "jpg";
                        form.set("file", record.attachment.file, `evidence.${extension}`);
                    }
                    requestUrl = `${apiBase()}/driver/pod`;
                    requestOptions = {
                        method: "POST",
                        credentials: "include",
                        body: form
                    };
                } else if (record.attachment) {
                    firstError = "This older queued attachment must be recaptured before it can sync.";
                    break;
                }
                const response = await fetch(requestUrl, requestOptions);
                if (!response.ok) {
                    let detail = "";
                    try {
                        const body = await response.json();
                        detail = typeof body.detail === "string" ? body.detail : "";
                    } catch (error) {
                        console.warn("Gateway returned an unreadable error response.", error);
                    }
                    throw new Error(detail || `Gateway rejected event (${response.status}).`);
                }
                await outboxTransaction("readwrite", (store) => store.delete(record.event_id));
                synced += 1;
                records = await outboxTransaction("readonly", (store) => store.getAll());
            } catch (error) {
                console.error("Driver event sync failed.", error);
                firstError = error.message || "The Gateway could not accept the event.";
                break;
            }
        }
    } catch (error) {
        console.error("Driver event sync failed.", error);
        firstError = error.message || "Sign in again to continue syncing.";
    } finally {
        syncAgain = state.syncRequested && !firstError;
        state.syncRequested = false;
        state.isSyncing = false;
    }
    await refreshOutboxCount();
    render();
    if (synced) notify(`${formatCount(synced, "event")} synced.`, "success");
    if (firstError) notify(`Sync paused: ${firstError}`, "error");
    if (heldForOtherAccount) {
        notify("Some queued actions belong to another or older session and were kept on this device.", "error");
    }
    if (syncAgain) await syncOutbox({ quiet: true });
    if (!synced && !firstError && !heldForOtherAccount && !quiet) {
        notify("Nothing to sync right now.", "success");
    }
}

export async function acceptRoute(routeId) {
    if (state.route) {
        notify("Finish or return your current route before accepting another.", "error");
        return;
    }
    let response;
    try {
        response = await apiRequest(`/driver/routes/${encodeURIComponent(routeId)}/accept`, {
            method: "POST",
            body: "{}"
        });
    } catch (error) {
        notify(error.message || "Could not start this route.", "error");
        return;
    }
    state.route = normalizeDriverRoute(response.route);
    state.driverProfile.status = response.driver_status;
    state.pickedUp = false;
    state.pickupScanned = new Set();
    state.stopScanned = new Set();
    state.completed = new Set();
    state.failed = new Set();
    state.arrived = new Set();
    try {
        await persistWorkState();
    } catch (error) {
        console.error("Could not persist the active route locally.", error);
        state.tab = "Route";
        render();
        notify(`Route started, but its offline state could not be saved: ${error.message}`, "error");
        return;
    }
    let eventQueueError = "";
    try {
        await queueEvent("route.started", { route_id: state.route.route_id });
    } catch (error) {
        console.error("Could not queue the route-start event.", error);
        eventQueueError = error.message;
    }
    state.tab = "Route";
    render();
    notify(
        eventQueueError
            ? `Route started, but its start event could not be queued: ${eventQueueError}`
            : "Assigned route started.",
        eventQueueError ? "error" : "success"
    );
}

function findScannedStop(code, orderId = null) {
    const normalized = code.trim().toUpperCase();
    return state.route?.stops.find((stop) => (
        stop.tracking_token?.trim().toUpperCase() === normalized
        && (!orderId || stop.order_id === orderId)
    )) || null;
}

async function verifyScannedStop(code, stage, stop) {
    const matchedStop = findScannedStop(code, stop?.order_id || null);
    if (!matchedStop) throw new Error("This barcode is not on the active route manifest.");
    if (navigator.onLine) {
        await apiRequest(`/driver/routes/${encodeURIComponent(state.route.route_id)}/scan`, {
            method: "POST",
            body: JSON.stringify({
                tracking_token: code.trim(),
                scan_stage: stage,
                ...(stop ? { order_id: stop.order_id } : {})
            })
        });
    }
    return matchedStop;
}

export async function scanPickupParcel() {
    if (!state.route || state.pickedUp) return;
    const code = await scanBarcode("Scan a parcel for pickup");
    if (!code) return;
    try {
        const stop = await verifyScannedStop(code, "pickup");
        if (state.pickupScanned.has(stop.order_id)) {
            notify("This parcel has already been scanned for pickup.", "info");
            return;
        }
        await queueEvent("package.scanned", {
            route_id: state.route.route_id,
            order_id: stop.order_id,
            tracking_token: stop.tracking_token,
            scan_stage: "pickup"
        });
        state.pickupScanned.add(stop.order_id);
        await persistWorkState();
        render();
        notify(`Parcel verified: ${stop.recipient}.`, "success");
    } catch (error) {
        notify(error.message || "Could not verify this parcel.", "error");
    }
}

export async function confirmPickup() {
    if (!state.route) return;
    if (state.pickupScanned.size !== state.route.stops.length) {
        notify("Scan every parcel on the route before confirming pickup.", "error");
        return;
    }
    try {
        await queueEvent("pickup.confirmed", {
            route_id: state.route.route_id,
            scanned_order_ids: state.route.stops.map((stop) => stop.order_id)
        });
        state.pickedUp = true;
        await persistWorkState();
        render();
        notify("Pickup confirmed. Scan history is queued for processing.", "success");
    } catch (error) {
        notify(error.message || "Could not save pickup confirmation.", "error");
    }
}

export function nextStop(orderId) {
    return state.route?.stops.find((stop) => stop.order_id === orderId) || null;
}

export async function arriveAtStop(orderId) {
    if (!state.pickedUp) {
        notify("Confirm the pickup handoff before starting deliveries.", "error");
        return;
    }
    const stop = nextStop(orderId);
    if (!stop) return;
    if (!state.stopScanned.has(orderId)) {
        notify("Scan the parcel assigned to this stop first.", "error");
        return;
    }
    try {
        await getLocation();
        await recordTelemetry("stop.arrived", { order_id: orderId });
        state.arrived.add(orderId);
        await persistWorkState();
        render();
        notify(`GPS check-in saved for ${stop.recipient}.`, "success");
    } catch (error) {
        notify(error.message, "error");
    }
}

export async function scanStopParcel(orderId) {
    const stop = nextStop(orderId);
    if (!stop || !state.pickedUp) return;
    const code = await scanBarcode(`Scan parcel for stop ${stop.sequence}`);
    if (!code) return;
    try {
        const matchedStop = await verifyScannedStop(code, "stop", stop);
        if (state.stopScanned.has(matchedStop.order_id)) {
            notify("This parcel has already been scanned for this stop.", "info");
            return;
        }
        await queueEvent("package.scanned", {
            route_id: state.route.route_id,
            order_id: matchedStop.order_id,
            tracking_token: matchedStop.tracking_token,
            scan_stage: "stop"
        });
        state.stopScanned.add(matchedStop.order_id);
        await persistWorkState();
        render();
        notify(`Parcel verified for ${matchedStop.recipient}.`, "success");
    } catch (error) {
        notify(error.message || "Could not verify this parcel.", "error");
    }
}

export function openDelivery(orderId) {
    const stop = nextStop(orderId);
    if (!stop) return;
    void captureProofOfDelivery(stop).then(async (proof) => {
        if (!proof) return;
        try {
            await getLocation();
            await queueEvent("pod.captured", {
                route_id: state.route.route_id,
                order_id: orderId,
                purpose: "pod"
            }, proof);
            await recordTelemetry("delivery.completed", { order_id: orderId });
            state.completed.add(orderId);
            state.arrived.delete(orderId);
            await persistWorkState();
            render();
            notify("Delivery saved. Proof and completion are queued in order.", "success");
        } catch (error) {
            notify(error.message || "Could not save delivery proof.", "error");
        }
    });
}

export function openException(orderId) {
    const stop = nextStop(orderId);
    if (!stop) return;
    void captureException(stop).then(async (exception) => {
        if (!exception) return;
        try {
            await getLocation();
            if (exception.photo instanceof Blob && exception.photo.size > 0) {
                await queueEvent("delivery.exception.evidence", {
                    route_id: state.route.route_id,
                    order_id: orderId,
                    purpose: "exception"
                }, {
                    evidenceType: "photo",
                    file: exception.photo,
                    recipientName: ""
                });
            }
            await recordTelemetry("delivery.failed", {
                order_id: orderId,
                failure_reason: exception.failureReason,
                ...(exception.failureNotes ? { failure_notes: exception.failureNotes } : {}),
                ...(exception.returnToHub ? { return_to_hub: true } : {})
            });
            state.failed.add(orderId);
            state.arrived.delete(orderId);
            await persistWorkState();
            render();
            notify(
                exception.returnToHub
                    ? "Exception saved; the order is marked returned. Return logistics are not tracked."
                    : "Exception saved; the order is marked for retry.",
                "success"
            );
        } catch (error) {
            notify(error.message || "Could not save the delivery exception.", "error");
        }
    });
}

export function openRouteDetails(routeId) {
    const route = state.driverRoutes.find((item) => item.route_id === routeId);
    if (!route) return;
    const driverStatus = state.driverProfile?.status;
    const vehicleMatches = state.driverProfile?.vehicle?.vehicle_id === route.vehicle_id;
    const canStart = driverStatus === "available" && vehicleMatches;
    const startMessage = driverStatus !== "available"
        ? `Your driver status is ${driverStatus || "unavailable"}; it must be available to start a route.`
        : "Your assigned vehicle must match this route's vehicle before you can start it.";
    const vehicle = state.driverProfile?.vehicle;
    const dialog = document.createElement("dialog");
    dialog.className = "action-dialog route-dialog";
    dialog.innerHTML = `<form method="dialog">
        <button class="dialog-close" type="button" data-action="close-dialog" aria-label="Close">×</button>
        <p class="eyebrow">ASSIGNED ROUTE</p><h2>${escapeHTML(route.title)}</h2>
        <p class="dialog-copy">${escapeHTML(route.area)} · ${route.stop_count} stops · ${route.distance_km} km · about ${Math.floor(route.duration_min / 60)}h ${route.duration_min % 60}m</p>
        <section class="route-detail-pickup"><span class="pickup-pin">⌖</span><div><small>PICKUP LOCATION</small><strong>${escapeHTML(route.pickup)}</strong></div></section>
        <section class="route-detail-pickup"><span class="pickup-pin">▰</span><div><small>ASSIGNED VEHICLE</small><strong>${escapeHTML(vehicle?.registration_number || "No vehicle linked")}${vehicle?.type ? ` · ${escapeHTML(vehicle.type.replaceAll("_", " "))}` : ""}</strong></div></section>
        <div class="route-dialog-map">${routeMap(route)}</div>
        <p class="field-hint">${escapeHTML(canStart ? "This route is assigned to your driver account. Starting it updates the live route and driver status." : startMessage)}</p>
        <p class="field-hint">Payout and parcel-capacity requirements are not included in this route assignment.</p>
        <button class="button button-primary button-wide" type="button" data-action="accept-route" data-route="${escapeHTML(route.route_id)}" ${canStart ? "" : "disabled"}>Start assigned route <span>→</span></button>
    </form>`;
    document.body.append(dialog);
    dialog.showModal();
    dialog.addEventListener("close", () => dialog.remove(), { once: true });
}

export async function startLocation() {
    try {
        const location = await getLocation();
        render();
        await recordTelemetry("driver.location.updated", {});
        notify(`GPS check-in saved · ${location.latitude.toFixed(4)}, ${location.longitude.toFixed(4)}`, "success");
    } catch (error) {
        notify(error.message, "error");
    }
}
