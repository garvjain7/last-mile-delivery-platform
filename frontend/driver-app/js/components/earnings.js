import { state, escapeHTML, formatCount } from "../state.js";
import { paymentMethodsView } from "./payment-methods.js";

function formatInr(value) {
    return new Intl.NumberFormat("en-IN", {
        style: "currency",
        currency: "INR",
        minimumFractionDigits: 2
    }).format(Number(value));
}

function formatTransactionDate(value) {
    return new Intl.DateTimeFormat("en-IN", {
        dateStyle: "medium",
        timeStyle: "short"
    }).format(new Date(value));
}

export function earningsView() {
    const delivered = state.completed.size;
    const totalStops = state.route?.stops.length || 0;
    const routeLabel = state.route?.title || "No active route";
    const earnings = state.earnings;
    const hasAvailableBalance = Number(earnings?.available_balance || 0) > 0;
    const transactions = earnings?.recent_transactions || [];
    const transactionsView = transactions.length
        ? transactions.map((transaction) => {
            const amount = Number(transaction.amount);
            const orderReference = transaction.order_id
                ? `Order ${transaction.order_id}`
                : "Wallet adjustment";
            return `
                <article class="earning-transaction">
                    <div class="earning-transaction-details">
                        <strong>${escapeHTML(orderReference)}</strong>
                        <small>${escapeHTML(formatTransactionDate(transaction.created_at))}</small>
                        <span>${escapeHTML(transaction.description)}</span>
                    </div>
                    <strong class="${amount < 0 ? "earning-debit" : "earning-credit"}">${escapeHTML(`${amount > 0 ? "+" : ""}${formatInr(amount)}`)}</strong>
                </article>`;
        }).join("")
        : earnings
            ? '<p class="field-hint">No earnings transactions yet.</p>'
            : `<p class="field-hint" role="status">${state.earningsError
                ? "Transaction history is unavailable until earnings data can be loaded."
                : "Loading earnings transactions…"}</p>`;
    const payoutStatus = !earnings
        ? state.earningsError || "Payout requests are unavailable while your ledger cannot be loaded."
        : hasAvailableBalance
            ? "Payout requests are not enabled yet. Your available balance remains in your wallet."
            : "Payout requests require posted ledger earnings and are not enabled yet.";

    return `
        <section class="page-heading">
            <p class="eyebrow">DRIVER SUMMARY</p>
            <h1>Earnings &amp; Wallet</h1>
            <p>Delivery pay and trusted operations adjustments.</p>
        </section>
        <section class="earnings-card">
            <span class="earnings-card-icon">₹</span>
            <p class="eyebrow">TOTAL AVAILABLE BALANCE</p>
            <h2>${earnings ? escapeHTML(formatInr(earnings.available_balance)) : "Unavailable"}</h2>
            <div class="earnings-hero-breakdown" aria-label="Available earnings breakdown">
                <div><span>Base pay</span><strong>${earnings ? escapeHTML(formatInr(earnings.base_pay)) : "Unavailable"}</strong></div>
                <div><span>Tips</span><strong>${earnings ? escapeHTML(formatInr(earnings.tips)) : "Unavailable"}</strong></div>
                <div><span>Bonuses</span><strong>${earnings ? escapeHTML(formatInr(earnings.bonuses)) : "Unavailable"}</strong></div>
            </div>
            <button class="button button-primary payout-request" type="button" disabled aria-describedby="payout-request-status">Request Payout</button>
            <p id="payout-request-status" class="payout-request-status">${escapeHTML(payoutStatus)}</p>
            ${!earnings && state.earningsError
                ? '<button class="button button-secondary finance-retry" type="button" data-action="refresh-financial-data">Retry earnings</button>'
                : ""}
            <span class="earnings-status">${earnings ? "INR WALLET" : "EARNINGS UNAVAILABLE"}</span>
        </section>
        <section class="wallet-breakdown" aria-label="Wallet earnings breakdown">
            <div class="section-heading"><div><p class="eyebrow">LEDGER SUMMARY</p><h3>Other totals</h3></div></div>
            <div class="wallet-line-item"><span>Adjustments</span><strong>${earnings ? escapeHTML(formatInr(earnings.adjustments)) : "Unavailable"}</strong></div>
            <div class="wallet-line-item"><span>Total earned</span><strong>${earnings ? escapeHTML(formatInr(earnings.total_earned)) : "Unavailable"}</strong></div>
            <p>Delivery pay is credited after a completed delivery is processed. Tips and other adjustments are posted by trusted operations.</p>
        </section>
        <section class="section-block earning-history">
            <div class="section-heading"><div><p class="eyebrow">LEDGER</p><h3>Transaction history</h3></div></div>
            ${transactionsView}
        </section>
        ${paymentMethodsView()}
        <section class="section-block earnings-activity">
            <div class="section-heading"><div><p class="eyebrow">DELIVERY ACTIVITY</p><h3>This shift</h3></div></div>
            <div class="earnings-metrics">
                <div><strong>${delivered}</strong><span>Delivered</span></div>
                <div><strong>${formatCount(totalStops, "stop")}</strong><span>Active route</span></div>
            </div>
            <p class="field-hint">${escapeHTML(routeLabel)}</p>
        </section>
        <section class="activity-summary earnings-sync">
            <span class="activity-summary-icon">↻</span>
            <div><strong>${state.outboxCount ? `${state.outboxCount} item${state.outboxCount === 1 ? "" : "s"} waiting to sync` : "Activity is synced"}</strong><small>Driver events are stored locally before sync.</small></div>
            <button class="button button-secondary button-small" data-action="sync">Sync</button>
        </section>
        <button class="text-button earnings-activity-link" data-tab="Activity">View activity history <span>→</span></button>`;
}
