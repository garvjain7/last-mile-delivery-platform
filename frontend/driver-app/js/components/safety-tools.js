import { escapeHTML, state } from "../state.js";
import { isCustomerCommunicationActive } from "./communications.js";

export function verificationPanel(stop) {
    const slots = Array.from({ length: 6 }, () => "<span aria-hidden=\"true\">·</span>").join("");
    return `<section class="verification-panel" aria-label="Delivery verification">
        <div><p class="eyebrow">SAFE HANDOFF</p><h3>Verify the delivery</h3></div>
        <p>Barcode scans are checked against your assigned route. Customer OTP verification is not connected.</p>
        <div class="otp-slots is-disabled" aria-label="One-time password entry unavailable">${slots}</div>
        <button class="button button-secondary button-wide" type="button" disabled aria-disabled="true">Enter customer OTP · unavailable</button>
        <small>Do not enter or share an OTP in this app until server-side verification is available.</small>
    </section>`;
}

export function sosButton() {
    const stop = state.route?.stops.find((item) => (
        !state.completed.has(item.order_id) && !state.failed.has(item.order_id)
    ));
    if (state.tab !== "Route" || !state.pickedUp || !isCustomerCommunicationActive(stop)) return "";
    return `<button class="sos-floating-button" type="button" data-action="confirm-sos" aria-label="Emergency SOS">
        <span aria-hidden="true">SOS</span><small>Emergency</small>
    </button>`;
}

export function showSosConfirmation() {
    if (!sosButton()) return;
    if (document.querySelector(".sos-confirmation-dialog")) return;
    const dialog = document.createElement("dialog");
    dialog.className = "action-dialog sos-confirmation-dialog";
    dialog.innerHTML = `<p class="eyebrow sos-eyebrow">EMERGENCY ASSISTANCE</p>
        <h2>Need help?</h2>
        <p class="dialog-copy">The dispatch emergency-alert service is not connected. No alert or location will be sent.</p>
        <div class="dialog-actions">
            <button class="button button-secondary" type="button" data-sos-cancel>Cancel</button>
            <button class="button button-sos-unavailable" type="button" disabled aria-disabled="true">Dispatch alert · unavailable</button>
        </div>
        <p class="dialog-footnote">If you are in immediate danger, contact local emergency services directly.</p>`;
    dialog.querySelector("[data-sos-cancel]").addEventListener("click", () => dialog.close());
    dialog.addEventListener("close", () => dialog.remove(), { once: true });
    document.body.append(dialog);
    dialog.showModal();
}

export function closeSosConfirmationIfInactive() {
    if (sosButton()) return;
    document.querySelectorAll(".sos-confirmation-dialog").forEach((dialog) => dialog.close());
}

export function isSosActive() {
    const stop = state.route?.stops.find((item) => (
        !state.completed.has(item.order_id) && !state.failed.has(item.order_id)
    ));
    return Boolean(state.tab === "Route" && state.pickedUp && isCustomerCommunicationActive(stop));
}

export function orderChecklist(stop) {
    if (!stop) return "";
    const scanned = state.stopScanned.has(stop.order_id);
    return `<section class="order-checklist" aria-label="Package checklist">
        <div class="section-heading"><div><p class="eyebrow">HANDOFF CHECKLIST</p><h3>Package for this stop</h3></div></div>
        <button class="order-check-row" type="button" data-action="scan-stop" data-order="${escapeHTML(stop.order_id)}"
            role="checkbox" aria-checked="${scanned}" ${scanned ? "disabled" : ""}>
            <span class="order-check-box" aria-hidden="true">${scanned ? "✓" : ""}</span>
            <span><strong>${escapeHTML(stop.recipient)}</strong><small>${escapeHTML(stop.tracking_token || "Tracking number unavailable")}</small></span>
            <span class="order-check-status">${scanned ? "Verified" : "Scan package"}</span>
        </button>
        <p>Item names and quantities are not included in the route response.</p>
    </section>`;
}
