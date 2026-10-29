import { state, escapeHTML } from "../state.js";

export function profileView() {
    const identity = state.identity || {};
    const assignedVehicle = state.driverProfile?.vehicle || null;
    const selected = assignedVehicle?.vehicle_id || "";
    let vehicleOptions = state.vehicles;
    if (assignedVehicle && !vehicleOptions.some((vehicle) => vehicle.vehicle_id === assignedVehicle.vehicle_id)) {
        vehicleOptions = [assignedVehicle, ...vehicleOptions];
    }
    return `<section class="page-heading"><p class="eyebrow">YOUR ACCOUNT</p><h1>Profile</h1><p>Keep your driver details and vehicle close at hand.</p></section>
        <section class="profile-card"><div class="profile-avatar">${escapeHTML((identity.full_name || "D").charAt(0).toUpperCase())}</div><div><h2>${escapeHTML(identity.full_name || "Driver")}</h2><p>${escapeHTML(identity.email || identity.phone || "Driver account")}</p></div><span class="profile-check">✓</span></section>
        <section class="section-block settings-section">
            <div class="section-heading"><div><p class="eyebrow">YOUR DETAILS</p><h3>Driver profile</h3></div></div>
            <label class="field-label" for="driver-full-name">Full name</label>
            <input id="driver-full-name" class="text-input" value="${escapeHTML(identity.full_name || "")}" maxlength="200" required>
            <label class="field-label" for="driver-phone">Phone</label>
            <input id="driver-phone" class="text-input" type="tel" value="${escapeHTML(identity.phone || "")}" placeholder="+919876543210">
        </section>
        <section class="section-block settings-section">
            <div class="section-heading"><div><p class="eyebrow">ON THE ROAD</p><h3>Vehicle</h3></div><span class="count-pill">Registration</span></div>
            <label class="field-label" for="vehicle-registration">Assigned vehicle</label>
            <div class="vehicle-search">
                <input id="vehicle-search" class="text-input" type="search" maxlength="100" placeholder="Search registration number">
                <button class="button button-secondary button-small" data-action="search-vehicles">Search</button>
            </div>
            <select id="vehicle-registration" class="select-input">
                <option value="">Select a vehicle</option>
                ${vehicleOptions.map((vehicle) => `<option value="${escapeHTML(vehicle.vehicle_id)}" ${selected === vehicle.vehicle_id ? "selected" : ""}>${escapeHTML(vehicle.registration_number)} · ${escapeHTML(vehicle.type.replaceAll("_", " "))}</option>`).join("")}
            </select>
            <p class="field-hint">Search and assignment use active vehicles available to this driver.</p>
        </section>
        <section class="section-block settings-section">
            <div class="section-heading"><div><p class="eyebrow">CONNECTION</p><h3>Sync settings</h3></div></div>
            <label class="field-label gateway-label" for="gateway-api-url">Driver Gateway URL (API + event sync)</label>
            <input id="gateway-api-url" class="text-input" type="url" value="${escapeHTML(state.settings.driverGatewayBase || window.location.origin)}">
            <p class="field-hint">Core API manages your centralized httpOnly session; the Driver App does not handle credentials. Authentication tokens are not exposed to page scripts.</p>
            <label class="field-label" for="google-maps-embed-key">Google Maps Embed API key</label>
            <input id="google-maps-embed-key" class="text-input" type="text" autocomplete="off" spellcheck="false" maxlength="200" value="${escapeHTML(state.settings.googleMapsEmbedKey || "")}" placeholder="Paste a Maps Embed API key">
            <p class="field-hint">Optional. Enables the in-app route map. This browser key is visible to app users; restrict it by website referrer and enable only Maps Embed API. Google Cloud project billing must be configured.</p>
            <button class="button button-secondary" data-action="save-profile-settings">Save settings</button>
        </section>
        <button class="profile-link-card" data-tab="Earnings"><span class="activity-summary-icon">₹</span><span><strong>Earnings & payouts</strong><small>Payout data is not connected to the driver API</small></span><b>→</b></button>
        <button class="profile-link-card" data-tab="Activity"><span class="activity-summary-icon">↻</span><span><strong>Activity & offline sync</strong><small>${state.outboxCount ? `${state.outboxCount} item${state.outboxCount === 1 ? "" : "s"} waiting` : "View recent driver actions"}</small></span><b>→</b></button>
        `;
}
