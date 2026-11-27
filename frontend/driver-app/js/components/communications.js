import { escapeHTML, notify, state } from "../state.js";

const QUICK_REPLIES = ["Stuck in traffic", "Need gate code", "I am outside"];
const IN_TRANSIT_STATUS = "out_for_delivery";

export function isCustomerCommunicationActive(stop) {
    return Boolean(
        state.route?.status === "in_progress"
        && stop?.order_status === IN_TRANSIT_STATUS
        && !state.completed.has(stop.order_id)
        && !state.failed.has(stop.order_id)
    );
}

export function customerCommunicationActions(stop) {
    if (!isCustomerCommunicationActive(stop)) {
        return `<p class="communication-status" role="status">Customer chat and masked calls unlock only while this order is In Transit (Out for delivery).</p>`;
    }
    return `<section class="customer-communication-actions" aria-label="Contact customer">
        <button class="button button-secondary" type="button" data-action="open-customer-chat" data-order="${escapeHTML(stop.order_id)}">
            <span aria-hidden="true">▤</span> Message customer
        </button>
        <button class="button button-call" type="button" disabled aria-disabled="true" title="Masked calling is not configured">
            <span aria-hidden="true">☎</span> Call · masked
        </button>
        <p>Masked calling provider is not configured. No direct phone call will be placed.</p>
    </section>`;
}

export function customerNoteUpdateBanner(stop) {
    if (!isCustomerCommunicationActive(stop)) return "";
    const update = state.customerNoteUpdates[stop.order_id];
    if (!update) return "";
    return `<aside class="customer-note-alert" role="alert">
        <div class="customer-note-alert-icon" aria-hidden="true">!</div>
        <div><strong>Customer updated delivery instructions</strong><p>${escapeHTML(update.notes)}</p></div>
        <button class="customer-note-dismiss" type="button" data-action="dismiss-customer-note" data-order="${escapeHTML(stop.order_id)}" aria-label="Dismiss customer note update">×</button>
    </aside>`;
}

export function receiveCustomerNoteUpdate(update) {
    if (
        !update
        || typeof update.order_id !== "string"
        || typeof update.notes !== "string"
        || !update.notes.trim()
    ) return false;
    const stop = state.route?.stops.find((item) => item.order_id === update.order_id);
    if (!stop || !isCustomerCommunicationActive(stop)) return false;
    state.customerNoteUpdates[stop.order_id] = {
        notes: update.notes.trim(),
        updatedAt: typeof update.updated_at === "string" ? update.updated_at : null
    };
    if (state.tab === "Route") document.dispatchEvent(new Event("driver:render"));
    return true;
}

export function dismissCustomerNoteUpdate(orderId) {
    delete state.customerNoteUpdates[orderId];
    if (state.tab === "Route") document.dispatchEvent(new Event("driver:render"));
}

export function openCustomerChat(orderId) {
    const stop = state.route?.stops.find((item) => item.order_id === orderId);
    if (!isCustomerCommunicationActive(stop)) {
        notify("Customer communications are only available while the order is Out for delivery.", "error");
        return;
    }
    if (document.querySelector(".customer-chat-dialog")) return;

    const dialog = document.createElement("dialog");
    dialog.className = "action-dialog customer-chat-dialog";
    dialog.dataset.orderId = stop.order_id;
    dialog.innerHTML = `<button class="dialog-close" type="button" data-chat-close aria-label="Close customer chat">×</button>
        <p class="eyebrow">CUSTOMER COMMUNICATION</p>
        <h2>Message ${escapeHTML(stop.recipient)}</h2>
        <p class="dialog-copy">${escapeHTML(stop.address)}</p>
        <div class="chat-lifecycle-badge"><span aria-hidden="true"></span> In Transit · Out for delivery</div>
        <section class="chat-message-list" aria-live="polite">
            <p class="chat-empty-state">Chat history is unavailable until a messaging service is connected.</p>
        </section>
        <fieldset class="quick-reply-fieldset">
            <legend>Quick replies</legend>
            <div class="quick-reply-list">${QUICK_REPLIES.map((reply) => `
                <button class="quick-reply-pill" type="button" data-quick-reply="${escapeHTML(reply)}">${escapeHTML(reply)}</button>
            `).join("")}</div>
        </fieldset>
        <label class="field-label" for="customer-message-draft">Message</label>
        <textarea id="customer-message-draft" class="text-input" rows="3" maxlength="500" placeholder="Choose a quick reply or write a message"></textarea>
        <p class="communication-integration-note">Messaging is not connected. Drafts are not sent or saved.</p>
        <button class="button button-primary button-wide" type="button" disabled aria-disabled="true">Send message · unavailable</button>`;

    const draft = dialog.querySelector("#customer-message-draft");
    dialog.querySelectorAll("[data-quick-reply]").forEach((button) => {
        button.addEventListener("click", () => {
            if (!isCustomerCommunicationActive(stop)) {
                closeCustomerChatIfInactive();
                return;
            }
            draft.value = button.dataset.quickReply;
        });
    });
    dialog.querySelector("[data-chat-close]").addEventListener("click", () => dialog.close());
    dialog.addEventListener("close", () => dialog.remove(), { once: true });
    document.body.append(dialog);
    dialog.showModal();
}

export function closeCustomerChatIfInactive(forceClose = false) {
    document.querySelectorAll(".customer-chat-dialog").forEach((dialog) => {
        const stop = state.route?.stops.find((item) => item.order_id === dialog.dataset.orderId);
        if (forceClose || !isCustomerCommunicationActive(stop)) dialog.close();
    });
}
