import { state } from "./state.js";

export function defaultDriverGatewayBase() {
    if (window.DRIVER_GATEWAY_URL) return window.DRIVER_GATEWAY_URL;
    const gatewayUrl = new URL(window.location.origin);
    if (gatewayUrl.port === "8000") gatewayUrl.port = "8002";
    return gatewayUrl.origin;
}

export function configuredDriverGatewayBase() {
    const savedBase = state.settings.driverGatewayBase;
    if (!savedBase || savedBase.replace(/\/+$/, "") === window.location.origin) {
        return defaultDriverGatewayBase();
    }
    return savedBase;
}

export function apiBase() {
    return configuredDriverGatewayBase().replace(/\/+$/, "");
}

export function normalizeDriverRoute(route) {
    const timeLabel = (timestamp) => {
        const date = new Date(timestamp);
        return Number.isNaN(date.getTime())
            ? "Arrival time unavailable"
            : date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
    };
    return {
        route_id: route.route_id,
        status: route.status,
        version: route.version,
        title: `Route ${String(route.route_id).slice(0, 8)}`,
        area: route.pickup_name,
        stop_count: route.stops.length,
        distance_km: route.total_distance_m == null ? 0 : Number((route.total_distance_m / 1000).toFixed(1)),
        duration_min: route.total_duration_s == null ? 0 : Math.round(route.total_duration_s / 60),
        pickup: route.pickup_name,
        pickup_address: route.pickup_address,
        pickup_latitude: route.pickup_latitude == null ? null : Number(route.pickup_latitude),
        pickup_longitude: route.pickup_longitude == null ? null : Number(route.pickup_longitude),
        pickup_code: route.pickup_code,
        vehicle_id: route.vehicle_id,
        vehicle_registration: route.vehicle_registration,
        stops: [...route.stops].sort((left, right) => left.sequence - right.sequence).map((stop) => ({
            route_stop_id: stop.route_stop_id,
            sequence: stop.sequence,
            order_id: stop.order_id,
            recipient: stop.recipient_name,
            order_status: stop.order_status,
            recipient_phone: stop.recipient_phone,
            address: stop.delivery_address,
            tracking_token: stop.tracking_token,
            latitude: stop.latitude == null ? null : Number(stop.latitude),
            longitude: stop.longitude == null ? null : Number(stop.longitude),
            window: stop.window_earliest && stop.window_latest
                ? `${timeLabel(stop.window_earliest)} – ${timeLabel(stop.window_latest)}`
                : timeLabel(stop.planned_arrival_at),
            status: stop.status
        }))
    };
}

export async function apiRequest(path, options = {}) {
    const request = {
        credentials: "include",
        ...options,
        headers: { "Content-Type": "application/json", ...(options.headers || {}) }
    };
    let response = await fetch(`${apiBase()}${path}`, request);
    if (
        response.status === 401
        && path !== "/auth/refresh"
    ) {
        const refresh = await fetch(`${apiBase()}/auth/refresh`, {
            method: "POST",
            credentials: "include",
            headers: { "Content-Type": "application/json" },
            body: "{}"
        });
        if (refresh.ok) response = await fetch(`${apiBase()}${path}`, request);
    }

    let body = {};
    if (response.status !== 204) {
        const rawText = await response.text();
        if (rawText) {
            try {
                body = JSON.parse(rawText);
            } catch (error) {
                if (response.ok) {
                    throw new Error("The service returned an unreadable response.");
                }
                body = { detail: rawText };
            }
        }
    }

    if (!response.ok) {
        const detail = body.detail;
        const message = typeof detail === "string" ? detail : "The request could not be completed.";
        const error = new Error(message);
        error.status = response.status;
        throw error;
    }
    return body;
}

export function getDriverEarnings() {
    return apiRequest("/driver/earnings");
}

export function getPaymentMethods() {
    return apiRequest("/driver/payment-methods");
}

export function createPaymentMethod(payload) {
    return apiRequest("/driver/payment-methods", {
        method: "POST",
        body: JSON.stringify(payload)
    });
}

export function setPreferredPaymentMethod(methodId) {
    return apiRequest(`/driver/payment-methods/${encodeURIComponent(methodId)}/preferred`, {
        method: "PUT"
    });
}
