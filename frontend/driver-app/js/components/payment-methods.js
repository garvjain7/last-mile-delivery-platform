import { escapeHTML, state } from "../state.js";

export function paymentMethodsView() {
    const methods = state.paymentMethods || [];
    const isLoading = state.financialDataLoading && !state.paymentMethodsError;
    const rows = state.paymentMethodsError
        ? ""
        : isLoading && !methods.length
        ? '<p class="field-hint" role="status">Loading payout methods…</p>'
        : methods.length
        ? methods.map((method) => `
            <div class="payment-method-row">
                <div>
                    <strong>${method.method_type === "upi" ? "UPI" : "Bank account"}</strong>
                    <small>${escapeHTML(method.masked_details)}</small>
                </div>
                ${method.is_preferred
                    ? '<span class="payment-preferred">Preferred</span>'
                    : `<button class="text-button" data-action="select-payment-method" data-payment-method="${escapeHTML(method.method_id)}">Make preferred</button>`}
            </div>`).join("")
        : '<p class="field-hint">No payout method saved yet.</p>';
    const refreshStatus = isLoading && methods.length
        ? '<p class="field-hint" role="status">Refreshing payout methods…</p>'
        : "";
    const methodError = state.paymentMethodsError
        ? `<div class="payment-error-block"><p class="payment-error" id="payment-methods-status" role="alert">${escapeHTML(state.paymentMethodsError)}</p>
            <button class="button button-secondary button-small finance-retry" data-action="refresh-financial-data" type="button">Retry payout methods</button></div>`
        : "";

    return `<section class="section-block settings-section payment-methods">
        <div class="section-heading">
            <div><p class="eyebrow">PAYOUT SETTINGS</p><h3>Payment methods</h3></div>
            <button class="button button-secondary button-small" data-action="open-payment-method-modal" type="button" ${state.paymentMethodsError ? 'disabled aria-describedby="payment-methods-status"' : ""}>Add / Update Payout Method</button>
        </div>
        ${methodError}
        ${state.paymentMethodsError ? "" : `${refreshStatus}<div class="payment-method-list">${rows}</div>`}
        <p class="field-hint">All financial records and account details are securely encrypted. Saved payout details are only shown in masked form.</p>
        ${state.paymentMethodsError ? "" : `
        <dialog id="payment-method-dialog" class="action-dialog payment-method-dialog" aria-labelledby="payment-method-dialog-title">
            <button class="dialog-close" type="button" data-action="close-dialog" aria-label="Close">×</button>
            <p class="eyebrow">SECURE PAYOUT SETTINGS</p>
            <h2 id="payment-method-dialog-title">Add or update payout method</h2>
            <p class="dialog-copy">New details are encrypted on the server. Select a saved method below to make it preferred.</p>
            <label class="field-label" for="payment-method-type">Payment method</label>
            <select id="payment-method-type" class="select-input">
                <option value="upi">UPI handle</option>
                <option value="bank_account">Bank account</option>
            </select>
            <div data-payment-fields="upi">
                <label class="field-label" for="payment-upi-id">UPI ID</label>
                <input id="payment-upi-id" class="text-input" type="text" maxlength="320" autocomplete="off" spellcheck="false" placeholder="name@bank">
            </div>
            <div data-payment-fields="bank_account" hidden>
                <label class="field-label" for="payment-account-holder">Account holder name</label>
                <input id="payment-account-holder" class="text-input" type="text" maxlength="200" autocomplete="off">
                <label class="field-label" for="payment-account-number">Account number</label>
                <input id="payment-account-number" class="text-input" type="password" inputmode="numeric" maxlength="18" autocomplete="off">
                <label class="field-label" for="payment-ifsc">IFSC code</label>
                <input id="payment-ifsc" class="text-input" type="text" maxlength="11" autocomplete="off" spellcheck="false">
            </div>
            <p class="field-hint">Transfers are not enabled; this saves a preferred payout destination only.</p>
            <div class="dialog-actions">
                <button class="button button-secondary" type="button" data-action="close-dialog">Cancel</button>
                <button class="button button-primary" type="button" data-action="add-payment-method">Save payout method</button>
            </div>
        </dialog>`}
    </section>`;
}
