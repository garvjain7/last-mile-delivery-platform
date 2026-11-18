import { state, escapeHTML, formatCount, notify, demoGpsPreviewEnabled } from "../state.js";
import {
    enqueueOutboxRecord,
    outboxTransaction,
    persistWorkState,
    refreshOutboxCount
} from "../storage.js";
import { apiBase, apiRequest, normalizeDriverRoute } from "../api.js";
import { render } from "../views.js";
import { routeMap } from "../components/routes.js";
import { scanBarcode, showScanWarning } from "../components/scanner.js";
import { captureException, captureProofOfDelivery } from "../components/pod.js";

const LOCATION_TELEMETRY_INTERVAL_MS = 30_000;
const LOCATION_TELEMETRY_MIN_DISTANCE_M = 50;
const DEMO_TRAVEL_DURATION_MS = 20_000;
const LOCATION_RENDER_INTERVAL_MS = 5_000;

let locationWatchId = null;
let demoLocationTimer = null;
let lastLocationEventAt = 0;
let lastLocationEvent = null;
let lastLocationRenderAt = 0;
let locationEventPending = false;

export function eventLocation() {
    return state.location ? { latitude: state.location.latitude, longitude: state.location.longitude } : null;
}

function distanceMeters(first, second) {
    const radians = (degrees) => degrees * Math.PI / 180;
    const latitudeDelta = radians(second.latitude - first.latitude);
    const longitudeDelta = radians(second.longitude - first.longitude);
    const firstLatitude = radians(first.latitude);
    const secondLatitude = radians(second.latitude);
    const haversine = Math.sin(latitudeDelta / 2) ** 2
        + Math.cos(firstLatitude) * Math.cos(secondLatitude) * Math.sin(longitudeDelta / 2) ** 2;
    return 6_371_000 * 2 * Math.atan2(Math.sqrt(haversine), Math.sqrt(1 - haversine));
}

async function queueLocationEvent(location) {
    if (!state.route || !state.driverUserId || locationEventPending) return;
    const now = Date.now();
    const movedEnough = lastLocationEvent
        && distanceMeters(lastLocationEvent, location) >= LOCATION_TELEMETRY_MIN_DISTANCE_M;
    if (
        lastLocationEvent
        && !movedEnough
        && now - lastLocationEventAt < LOCATION_TELEMETRY_INTERVAL_MS
    ) return;

    locationEventPending = true;
    try {
        await queueEvent("driver.location.updated", {
            latitude: location.latitude,
            longitude: location.longitude,
            current_route_id: state.route.route_id
        });
        lastLocationEvent = { latitude: location.latitude, longitude: location.longitude };
        lastLocationEventAt = now;
    } finally {
        locationEventPending = false;
    }
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
    if (state.locationMode === "demo") stopDemoLocationSimulation();
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

export function stopLocationTracking() {
    if (locationWatchId !== null) {
        navigator.geolocation.clearWatch(locationWatchId);
        locationWatchId = null;
    }
    if (state.locationMode === "live") {
        state.locationMode = "off";
        state.locationStatus = state.location
            ? "Live GPS tracking paused"
            : "Location not shared";
    }
}

export function stopDemoLocationSimulation({ notifyUser = false } = {}) {
    if (demoLocationTimer !== null) {
        window.clearInterval(demoLocationTimer);
        demoLocationTimer = null;
    }
    state.demoLocation = null;
    state.demoProgress = null;
    if (state.locationMode === "demo") {
        state.locationMode = "off";
        state.locationStatus = "Location not shared";
    }
    if (notifyUser) notify("Demo GPS preview stopped. No simulated location was sent.", "info");
}

export function startDemoLocationSimulation() {
    if (!demoGpsPreviewEnabled()) {
        notify("Demo GPS preview is disabled for this app session.", "error");
        return;
    }
    if (state.locationMode === "demo") {
        stopDemoLocationSimulation({ notifyUser: true });
        render();
        return;
    }
    if (!state.route || !state.pickedUp) {
        notify("Start a route and confirm pickup before previewing the demo drive.", "error");
        return;
    }

    const target = state.route.stops.find((stop) => (
        !state.completed.has(stop.order_id) && !state.failed.has(stop.order_id)
    ));
    if (!target || !Number.isFinite(target.latitude) || !Number.isFinite(target.longitude)) {
        notify("The next stop has no route coordinates for a GPS preview.", "error");
        return;
    }
    if (!Number.isFinite(state.route.pickup_latitude) || !Number.isFinite(state.route.pickup_longitude)) {
        notify("The route pickup has no coordinates for a GPS preview.", "error");
        return;
    }

    stopLocationTracking();
    if (demoLocationTimer !== null) window.clearInterval(demoLocationTimer);
    const start = {
        latitude: state.route.pickup_latitude,
        longitude: state.route.pickup_longitude
    };
    const startedAt = Date.now();
    state.locationMode = "demo";
    state.locationStatus = "Demo GPS preview · local only";
    state.demoLocation = { ...start, timestamp: new Date(startedAt).toISOString() };
    state.demoProgress = 0;
    render();

    demoLocationTimer = window.setInterval(() => {
        const progress = Math.min((Date.now() - startedAt) / DEMO_TRAVEL_DURATION_MS, 1);
        state.demoProgress = progress;
        state.demoLocation = {
            latitude: start.latitude + (target.latitude - start.latitude) * progress,
            longitude: start.longitude + (target.longitude - start.longitude) * progress,
            timestamp: new Date().toISOString()
        };
        render();
        if (progress === 1) {
            window.clearInterval(demoLocationTimer);
            demoLocationTimer = null;
            notify(`Demo preview reached ${target.recipient}'s stop. This location was not sent to the Gateway.`, "info");
        }
    }, 500);
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
    const nextStop = state.route.stops.find((stop) => !state.pickupScanned.has(stop.order_id));
    const code = await scanBarcode("Scan a parcel for pickup", nextStop?.tracking_token || "");
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
        showScanWarning(error.message || "Could not verify this parcel.");
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
    const code = await scanBarcode(`Scan parcel for stop ${stop.sequence}`, stop.tracking_token || "");
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
        showScanWarning(error.message || "Could not verify this parcel.");
    }
}

export function openDelivery(orderId) {
    const stop = nextStop(orderId);
    if (!stop) return;
    void captureProofOfDelivery(stop, state.stopScanned.has(orderId)).then(async (proof) => {
        if (!proof) return;
        try {
            await getLocation();
            const evidenceDetails = {
                route_id: state.route.route_id,
                order_id: orderId,
                purpose: "pod"
            };
            await queueEvent("pod.captured", evidenceDetails, {
                evidenceType: "photo",
                file: proof.file,
                recipientName: proof.recipientName
            });
            if (proof.signatureFile) {
                await queueEvent("pod.captured", evidenceDetails, {
                    evidenceType: "signature",
                    file: proof.signatureFile
                });
            }
            await recordTelemetry("delivery.completed", { order_id: orderId });
            state.completed.add(orderId);
            state.arrived.delete(orderId);
            delete state.customerNoteUpdates[orderId];
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
            delete state.customerNoteUpdates[orderId];
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
        <section class="route-window-list" aria-label="Scheduled delivery windows">
            <div><strong>Delivery windows</strong><small>Priority flags are not provided by the route service.</small></div>
            ${route.stops.slice(0, 3).map((stop) => `<p><span aria-hidden="true">◷</span><strong>Stop ${stop.sequence}</strong><span>${escapeHTML(stop.window)}</span></p>`).join("")}
            ${route.stops.length > 3 ? `<small>+ ${route.stops.length - 3} more stops in the route manifest</small>` : ""}
        </section>
        <div class="route-dialog-map">${routeMap(route)}</div>
        <p class="field-hint">${escapeHTML(canStart ? "This route is assigned to your driver account. Starting it updates the live route and driver status." : startMessage)}</p>
        <p class="field-hint">Payout and parcel-capacity requirements are not included in this route assignment.</p>
        ${canStart ? `<label class="route-swipe-label" for="route-start-slider">Slide to start this assigned route</label>
            <input id="route-start-slider" class="route-start-slider" type="range" min="0" max="100" value="0" step="1" aria-label="Slide to start this assigned route" aria-valuetext="Not started" data-route-start="${escapeHTML(route.route_id)}">
            <p class="route-swipe-hint" data-route-start-hint>Slide to the end to start · keyboard-accessible</p>` : ""}
        <button class="button button-primary button-wide" type="button" data-action="accept-route" data-route="${escapeHTML(route.route_id)}" ${canStart ? "" : "disabled"}>Start assigned route <span>→</span></button>
    </form>`;
    document.body.append(dialog);
    dialog.showModal();
    dialog.addEventListener("close", () => dialog.remove(), { once: true });
}

export async function startLocation() {
    if (locationWatchId !== null) {
        stopLocationTracking();
        render();
        notify("Live GPS tracking paused.", "info");
        return;
    }
    stopDemoLocationSimulation();
    if (!("geolocation" in navigator)) {
        notify("This device does not support live GPS tracking.", "error");
        return;
    }

    lastLocationEventAt = 0;
    lastLocationEvent = null;
    lastLocationRenderAt = 0;
    state.locationMode = "live";
    state.locationStatus = "Waiting for a live GPS fix…";
    render();
    try {
        locationWatchId = navigator.geolocation.watchPosition((position) => {
            state.location = {
                latitude: position.coords.latitude,
                longitude: position.coords.longitude,
                accuracy: position.coords.accuracy,
                timestamp: new Date(position.timestamp).toISOString()
            };
            state.locationStatus = `Live GPS · ±${Math.round(position.coords.accuracy)} m`;
            if (Date.now() - lastLocationRenderAt >= LOCATION_RENDER_INTERVAL_MS) {
                lastLocationRenderAt = Date.now();
                render();
            }
            void queueLocationEvent(state.location).catch((error) => {
                console.error("Could not queue live GPS telemetry.", error);
                notify("Live GPS could not be queued. The location is still updating on this device.", "error");
            });
        }, (error) => {
            if (locationWatchId !== null) navigator.geolocation.clearWatch(locationWatchId);
            locationWatchId = null;
            state.locationMode = "off";
            state.locationStatus = "Live GPS unavailable";
            render();
            const messages = {
                1: "Allow location access to share live GPS.",
                2: "GPS could not determine your location. Try again outdoors.",
                3: "GPS request timed out. Try again."
            };
            notify(messages[error.code] || "Unable to access live GPS.", "error");
        }, { enableHighAccuracy: true, timeout: 15_000, maximumAge: 5_000 });
    } catch (error) {
        state.locationMode = "off";
        state.locationStatus = "Live GPS unavailable";
        render();
        notify(error.message || "Unable to start live GPS tracking.", "error");
    }
}
