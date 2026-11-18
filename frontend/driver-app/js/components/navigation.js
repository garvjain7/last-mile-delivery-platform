import { state, escapeHTML } from "../state.js";
import { brandMark } from "./brand.js";

export function topbar() {
    const name = state.identity?.full_name || "Driver";
    const connected = navigator.onLine;
    const connection = navigator.connection;
    const lowSignal = connected && (
        ["slow-2g", "2g"].includes(connection?.effectiveType)
        || (Number.isFinite(connection?.downlink) && connection.downlink < 0.5)
    );
    const networkLabel = !connected ? "Offline · saved on device" : lowSignal ? "Low signal" : "Online";
    const hub = state.route?.pickup || state.driverProfile?.vehicle?.registration_number;
    return `
        <header class="topbar">
            <a class="brand-lockup" href="#" data-action="go-home" aria-label="LastMile driver home">${brandMark("brand-symbol")}<span class="brand-wordmark"><strong>LastMile</strong><small>DRIVER CONSOLE</small></span></a>
            ${hub ? `<span class="workspace-context">${escapeHTML(hub)}</span>` : ""}
            <div class="topbar-right">
                <button class="sync-indicator ${!connected ? "is-offline" : lowSignal ? "is-low-signal" : ""}" data-action="sync" title="Connection status and queued event sync" aria-label="${networkLabel}${state.outboxCount ? `, ${state.outboxCount} queued` : ""}. Sync events">
                    <span class="sync-dot" aria-hidden="true"></span><span>${networkLabel}</span>${state.outboxCount ? `<b>${state.outboxCount}</b>` : ""}
                </button>
                <button class="topbar-activity" data-tab="Activity" aria-label="Open activity and sync queue"><span aria-hidden="true">↻</span><span>Activity</span>${state.outboxCount ? `<b>${state.outboxCount}</b>` : ""}</button>
                <button class="text-button compact-logout" data-action="logout-driver-app" aria-label="Log out of driver app">Log out</button>
                <button class="avatar-button" data-tab="Profile" aria-label="Open profile"><span aria-hidden="true">${escapeHTML(name.charAt(0).toUpperCase())}</span><small>Profile</small></button>
            </div>
        </header>`;
}

export function greeting() {
    const hour = new Date().getHours();
    const welcome = hour < 12 ? "Good morning" : hour < 18 ? "Good afternoon" : "Good evening";
    return `${welcome}, ${escapeHTML((state.identity?.full_name || "Driver").split(" ")[0])}.`;
}
