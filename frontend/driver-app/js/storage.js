import { state, showError } from "./state.js";

export const DB_NAME = "fieldnote-driver";

export const DB_VERSION = 2;

export const OUTBOX_STORE = "outbox";

export const APP_STATE_STORE = "app-state";

export async function openDatabase() {
    return new Promise((resolve, reject) => {
        const request = indexedDB.open(DB_NAME, DB_VERSION);
        request.onupgradeneeded = () => {
            const database = request.result;
            if (!database.objectStoreNames.contains(OUTBOX_STORE)) {
                database.createObjectStore(OUTBOX_STORE, { keyPath: "event_id" });
            }
            if (!database.objectStoreNames.contains(APP_STATE_STORE)) {
                database.createObjectStore(APP_STATE_STORE, { keyPath: "id" });
            }
        };
        request.onsuccess = () => resolve(request.result);
        request.onerror = () => reject(request.error || new Error("Unable to open offline storage."));
        request.onblocked = () => reject(new Error("Offline storage is blocked by another app tab."));
    });
}

export function outboxTransaction(mode, action) {
    return new Promise((resolve, reject) => {
        if (!state.db) {
            reject(new Error("Offline storage is not available."));
            return;
        }
        const transaction = state.db.transaction(OUTBOX_STORE, mode);
        const request = action(transaction.objectStore(OUTBOX_STORE));
        let result;
        request.onsuccess = () => { result = request.result; };
        request.onerror = () => reject(request.error || new Error("Offline queue operation failed."));
        transaction.oncomplete = () => resolve(result);
        transaction.onabort = () => reject(transaction.error || new Error("Offline queue transaction failed."));
    });
}

export function appStateTransaction(mode, action) {
    return new Promise((resolve, reject) => {
        if (!state.db) {
            reject(new Error("Offline storage is not available."));
            return;
        }
        const transaction = state.db.transaction(APP_STATE_STORE, mode);
        const request = action(transaction.objectStore(APP_STATE_STORE));
        let result;
        request.onsuccess = () => { result = request.result; };
        request.onerror = () => reject(request.error || new Error("Route state operation failed."));
        transaction.oncomplete = () => resolve(result);
        transaction.onabort = () => reject(transaction.error || new Error("Route state transaction failed."));
    });
}

export function enqueueOutboxRecord(record) {
    return new Promise((resolve, reject) => {
        if (!state.db) {
            reject(new Error("Offline storage is not available."));
            return;
        }
        const transaction = state.db.transaction([OUTBOX_STORE, APP_STATE_STORE], "readwrite");
        const outbox = transaction.objectStore(OUTBOX_STORE);
        const appState = transaction.objectStore(APP_STATE_STORE);
        const sequenceRequest = appState.get("outbox-sequence");
        let queuedRecord;
        sequenceRequest.onerror = () => reject(sequenceRequest.error || new Error("Could not sequence offline actions."));
        sequenceRequest.onsuccess = () => {
            const queue_sequence = (Number(sequenceRequest.result?.value) || 0) + 1;
            queuedRecord = { ...record, queue_sequence };
            appState.put({ id: "outbox-sequence", value: queue_sequence });
            const addRequest = outbox.add(queuedRecord);
            addRequest.onerror = () => reject(addRequest.error || new Error("Could not save offline action."));
        };
        transaction.oncomplete = () => resolve(queuedRecord);
        transaction.onabort = () => reject(transaction.error || new Error("Offline queue transaction failed."));
    });
}

export async function persistWorkState() {
    const snapshot = {
        id: "active-route",
        route: state.route,
        pickedUp: state.pickedUp,
        pickupScanned: [...state.pickupScanned],
        stopScanned: [...state.stopScanned],
        completed: [...state.completed],
        failed: [...state.failed],
        arrived: [...state.arrived]
    };
    await appStateTransaction("readwrite", (store) => store.put(snapshot));
}

export async function restoreWorkState() {
    const snapshot = await appStateTransaction("readonly", (store) => store.get("active-route"));
    if (!snapshot) return;
    state.route = snapshot.route || null;
    state.pickedUp = Boolean(snapshot.pickedUp);
    state.pickupScanned = new Set(snapshot.pickupScanned || []);
    state.stopScanned = new Set(snapshot.stopScanned || []);
    state.completed = new Set(snapshot.completed || []);
    state.failed = new Set(snapshot.failed || []);
    state.arrived = new Set(snapshot.arrived || []);
    if (state.route) state.tab = "Route";
}

export async function clearWorkState() {
    await appStateTransaction("readwrite", (store) => store.delete("active-route"));
}

export async function removeLegacyDemoData() {
    if (!state.db) throw new Error("Offline storage is not available.");
    await new Promise((resolve, reject) => {
        const transaction = state.db.transaction([OUTBOX_STORE, APP_STATE_STORE], "readwrite");
        const outbox = transaction.objectStore(OUTBOX_STORE);
        const appState = transaction.objectStore(APP_STATE_STORE);
        const recordsRequest = outbox.getAll();
        const routeRequest = appState.get("active-route");
        recordsRequest.onsuccess = () => {
            for (const record of recordsRequest.result) {
                if (record.demo) outbox.delete(record.event_id);
            }
        };
        routeRequest.onsuccess = () => {
            if (routeRequest.result?.route?.is_demo) appState.delete("active-route");
        };
        recordsRequest.onerror = () => reject(recordsRequest.error || new Error("Could not remove saved sample actions."));
        routeRequest.onerror = () => reject(routeRequest.error || new Error("Could not remove the saved sample route."));
        transaction.oncomplete = () => resolve();
        transaction.onerror = () => reject(transaction.error || new Error("Could not clean saved sample data."));
        transaction.onabort = () => reject(transaction.error || new Error("Could not clean saved sample data."));
    });
}

export async function refreshOutboxCount() {
    try {
        const records = await outboxTransaction("readonly", (store) => store.getAll());
        state.outboxCount = records.length;
    } catch (error) {
        console.error("Could not read the offline queue.", error);
        showError("Offline queue unavailable. Actions cannot be saved safely.");
    }
}
