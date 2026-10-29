import { state, escapeHTML } from "../state.js";
import { brandMark } from "./brand.js";

export function topbar() {
    const name = state.identity?.full_name || "Driver";
    const connected = navigator.onLine;
    const hub = state.route?.pickup || state.driverProfile?.vehicle?.registration_number;
    return `
        <header class="topbar">
            <a class="brand-lockup" href="#" data-action="go-home" aria-label="LastMile driver home">${brandMark("brand-symbol")}<span class="brand-wordmark"><strong>LastMile</strong><small>DRIVER CONSOLE</small></span></a>
            ${hub ? `<span class="workspace-context">${escapeHTML(hub)}</span>` : ""}
            <div class="topbar-right">
                <button class="sync-indicator ${connected ? "" : "is-offline"}" data-action="sync" title="Connection status and queued event sync" aria-label="${connected ? "Online" : "Offline"}${state.outboxCount ? `, ${state.outboxCount} queued` : ""}. Sync events">
                    <span class="sync-dot"></span><span>${connected ? "Online" : "Offline"}</span>${state.outboxCount ? `<b>${state.outboxCount}</b>` : ""}
                </button>
                <button class="avatar-button" data-tab="Profile" aria-label="Open profile">${escapeHTML(name.charAt(0).toUpperCase())}</button>
            </div>
        </header>`;
}

export function greeting() {
    const hour = new Date().getHours();
    const welcome = hour < 12 ? "Good morning" : hour < 18 ? "Good afternoon" : "Good evening";
    return `${welcome}, ${escapeHTML((state.identity?.full_name || "Driver").split(" ")[0])}.`;
}
