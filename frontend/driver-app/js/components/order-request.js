import { escapeHTML, notify, state } from "../state.js";
import { acceptRoute } from "../services/driver-events.js";

function metric(value, suffix = "") {
    return Number.isFinite(value) && value >= 0 ? `${value.toFixed(1)}${suffix}` : "Not provided";
}

function payout(value, currency) {
    if (!Number.isFinite(value) || value < 0 || typeof currency !== "string" || !currency.trim()) {
        return "Not provided";
    }
    try {
        return new Intl.NumberFormat(undefined, {
            style: "currency",
            currency,
            maximumFractionDigits: 2
        }).format(value);
    } catch (error) {
        console.warn("Order request used an unsupported payout currency.", error);
        return "Not provided";
    }
}

export function showOrderRequest(request) {
    const assignedRoute = state.driverRoutes.find((route) => route.route_id === request?.route_id);
    const expiresAt = Date.parse(request?.expires_at);
    if (state.route) {
        notify("Finish your active route before reviewing another request.", "error");
        return;
    }
    if (
        !request
        || typeof request.route_id !== "string"
        || !assignedRoute
        || assignedRoute.status !== "planned"
        || !Number.isFinite(expiresAt)
        || expiresAt <= Date.now()
    ) {
        notify("This request is not an eligible assigned route or its acceptance window has expired.", "error");
        return;
    }
    document.querySelectorAll(".order-request-overlay").forEach((overlay) => overlay.remove());

    const overlay = document.createElement("dialog");
    overlay.className = "order-request-overlay";
    overlay.setAttribute("aria-label", "New assigned delivery request");
    overlay.innerHTML = `<section class="order-request-card">
        <div class="order-request-header"><p class="eyebrow">NEW ASSIGNED ROUTE</p><span>REVIEW BEFORE ACCEPTING</span></div>
        <h2>${escapeHTML(assignedRoute.title)}</h2>
        <p class="order-request-area">${escapeHTML(assignedRoute.area)}</p>
        <div class="request-metrics">
            <div><span>Distance to pickup</span><strong>${metric(request.distance_to_pickup_km, " km")}</strong></div>
            <div><span>Distance to customer</span><strong>${metric(request.distance_to_customer_km, " km")}</strong></div>
            <div><span>Estimated payout</span><strong>${escapeHTML(payout(request.estimated_payout_amount, request.currency))}</strong></div>
            <div><span>Route stops</span><strong>${assignedRoute.stop_count}</strong></div>
        </div>
        <div class="request-countdown" role="timer" aria-live="off">
            <div class="request-countdown-ring"><span data-request-countdown>--</span></div>
            <strong>Time to respond</strong>
        </div>
        <p class="request-expired-message" data-request-expired hidden>The acceptance window expired.</p>
        <div class="request-actions">
            <button class="button button-secondary" type="button" data-request-dismiss>Not now</button>
            <button class="button button-primary" type="button" data-request-accept>Accept assigned route</button>
        </div>
        <label class="request-swipe-label" for="request-accept-slider">Or slide to accept</label>
        <input id="request-accept-slider" class="request-accept-slider" type="range" min="0" max="100" value="0" step="1" aria-label="Slide to accept assigned route">
        <p class="request-data-note">Request details are supplied by the future route-request integration. Payout and distances are not inferred.</p>
    </section>`;

    const countdown = overlay.querySelector("[data-request-countdown]");
    const accept = overlay.querySelector("[data-request-accept]");
    const acceptSlider = overlay.querySelector("[data-request-accept-slider]");
    const expirationMessage = overlay.querySelector("[data-request-expired]");
    const duration = expiresAt - Date.now();
    const dismiss = () => {
        window.clearInterval(timer);
        overlay.close();
    };
    const updateCountdown = () => {
        const remaining = Math.max(0, Math.ceil((expiresAt - Date.now()) / 1000));
        countdown.textContent = String(remaining);
        overlay.style.setProperty(
            "--request-countdown-progress",
            `${Math.max(0, Math.min(360, (remaining * 1000 / duration) * 360))}deg`
        );
        if (!remaining) {
            accept.disabled = true;
            acceptSlider.disabled = true;
            expirationMessage.hidden = false;
            window.clearInterval(timer);
        }
    };
    const timer = window.setInterval(updateCountdown, 250);
    overlay.querySelector("[data-request-dismiss]").addEventListener("click", dismiss);
    const acceptAssignedRoute = async () => {
        if (Date.now() >= expiresAt || state.route) {
            updateCountdown();
            if (state.route) notify("Finish your active route before accepting another.", "error");
            return;
        }
        accept.disabled = true;
        acceptSlider.disabled = true;
        window.clearInterval(timer);
        overlay.close();
        await acceptRoute(assignedRoute.route_id);
    };
    accept.addEventListener("click", acceptAssignedRoute);
    acceptSlider.addEventListener("change", () => {
        if (acceptSlider.value === "100") void acceptAssignedRoute();
    });
    overlay.addEventListener("close", () => {
        window.clearInterval(timer);
        overlay.remove();
    }, { once: true });
    document.body.append(overlay);
    overlay.showModal();
    updateCountdown();
}
