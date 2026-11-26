import { requestJson, ApiError } from './api.js';

let activePage = null;
let toastTimer = null;

function shellMarkup() {
  return `
    <div id="bootstrap-error" class="bootstrap-screen" hidden>
      <section class="bootstrap-card" aria-labelledby="bootstrap-title">
        <div class="brand-mark" aria-hidden="true">L</div>
        <h1 id="bootstrap-title">Admin console unavailable</h1>
        <p id="bootstrap-message" class="muted">We couldn’t load your account. Try again.</p>
        <button id="bootstrap-retry" class="button button-primary" type="button">Try again</button>
      </section>
    </div>
    <main id="access-denied" class="access-denied" hidden>
      <section class="bootstrap-card" aria-labelledby="denied-title">
        <div class="brand-mark" aria-hidden="true">L</div>
        <h1 id="denied-title">Access denied</h1>
        <p class="muted">Your account does not have permission to use the admin console.</p>
        <a class="button button-secondary" href="/">Return to LOGIPULSE</a>
      </section>
    </main>
    <div id="admin-shell" class="admin-shell" hidden>
      <aside class="sidebar" aria-label="Admin navigation">
        <a class="brand" href="/admin" aria-label="LOGIPULSE admin overview">
          <span class="brand-mark" aria-hidden="true">L</span>
          <span class="brand-copy"><strong>LOGIPULSE</strong><small>ADMIN CONSOLE</small></span>
        </a>
        <div class="nav-heading">MENU</div>
        <nav id="primary-nav" class="primary-nav" aria-label="Primary">
          <a class="nav-link" href="/admin" data-page="overview"><span>Overview</span></a>
          <a class="nav-link" href="/admin/drivers" data-page="drivers"><span>Drivers</span></a>
          <a class="nav-link" href="/admin/users" data-page="users"><span>Users</span></a>
          <a class="nav-link" href="/admin/merchants" data-page="merchants"><span>Merchants</span></a>
          <a class="nav-link" href="/admin/warehouses" data-page="warehouses"><span>Warehouses</span></a>
          <a class="nav-link" href="/admin/orders" data-page="orders"><span>Orders</span></a>
          <a class="nav-link" href="/admin/activity" data-page="activity"><span>Activity</span></a>
        </nav>
        <section class="sidebar-footer" aria-label="Signed-in administrator">
          <div class="account-avatar" id="account-avatar" aria-hidden="true">A</div>
          <div class="account-copy"><strong id="account-name">Administrator</strong><span id="account-email"></span></div>
          <button id="logout-button" class="icon-button logout-button" type="button" aria-label="Sign out" title="Sign out"><svg aria-hidden="true" viewBox="0 0 24 24"><path d="M10 17l5-5-5-5M15 12H3m9-9h6a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2h-6"/></svg></button>
        </section>
      </aside>
      <div class="admin-content">
        <header class="topbar">
          <div class="topbar-title"><p class="eyebrow">PLATFORM CONTROL</p><h1 id="page-title"></h1></div>
          <div class="topbar-actions">
            <span class="refresh-meta" id="last-refreshed">Awaiting platform data</span>
            <button id="refresh-button" class="button button-secondary refresh-button" type="button">Refresh</button>
          </div>
        </header>
        <main id="page-content" class="page-content" aria-busy="false"></main>
        <div id="toast-region" class="toast-region" aria-live="polite" aria-atomic="true"></div>
      </div>
    </div>`;
}

export function setActivePage(page) {
  activePage = page;
}

export function showToast(message, tone = 'success') {
  const region = document.getElementById('toast-region');
  if (!region) return;
  region.replaceChildren();
  const toast = document.createElement('div');
  toast.className = `toast${tone === 'error' ? ' error' : ''}`;
  toast.setAttribute('role', tone === 'error' ? 'alert' : 'status');
  toast.textContent = message;
  region.append(toast);
  if (toastTimer) window.clearTimeout(toastTimer);
  toastTimer = window.setTimeout(() => toast.remove(), 4600);
}

function setRefreshed(at) {
  if (!(at instanceof Date) || Number.isNaN(at.getTime())) return;
  const node = document.getElementById('last-refreshed');
  if (!node) return;
  node.textContent = `Last refreshed ${new Intl.DateTimeFormat(undefined, {
    timeZone: window.adminTimezone || 'Asia/Kolkata', hour: 'numeric', minute: '2-digit'
  }).format(at)}`;
  node.title = `Browser fetch completed at ${at.toISOString()}`;
}

function showStartupError(message) {
  const error = document.getElementById('bootstrap-error');
  document.getElementById('bootstrap-message').textContent = message;
  error.hidden = false;
  document.getElementById('access-denied').hidden = true;
  document.getElementById('admin-shell').hidden = true;
}

function showAccessDenied() {
  document.getElementById('access-denied').hidden = false;
  document.getElementById('bootstrap-error').hidden = true;
  document.getElementById('admin-shell').hidden = true;
}

export async function bootstrapShell(page) {
  const app = document.getElementById('app');
  app.innerHTML = shellMarkup();
  const startupError = document.getElementById('bootstrap-error');
  const retry = document.getElementById('bootstrap-retry');
  let busy = false;
  const start = async () => {
    if (busy) return null;
    busy = true;
    startupError.hidden = true;
    try {
      const me = await requestJson('/api/admin/me');
      if (!Array.isArray(me.roles) || !me.roles.includes('admin')) {
        showAccessDenied();
        return null;
      }
      window.adminTimezone = typeof me.app_timezone === 'string' && me.app_timezone ? me.app_timezone : 'Asia/Kolkata';
      document.getElementById('account-name').textContent = me.full_name || 'Administrator';
      document.getElementById('account-email').textContent = me.email || 'No email on account';
      document.getElementById('account-avatar').textContent = (me.full_name || 'A').trim().charAt(0).toUpperCase();
      document.getElementById('page-title').textContent = page.title;
      document.querySelector(`#primary-nav [data-page="${page.name}"]`)?.setAttribute('aria-current', 'page');
      document.getElementById('refresh-button').hidden = page.name !== 'overview';
      document.getElementById('last-refreshed').hidden = page.name !== 'overview';
      document.getElementById('admin-shell').hidden = false;
      return {
        api: {
          get: (path, options) => requestJson(path, options),
          post: async (path, body) => requestJson(path, { method: 'POST', body }),
          patch: async (path, body) => requestJson(path, { method: 'PATCH', body }),
          delete: async (path) => requestJson(path, { method: 'DELETE', body: {} })
        },
        me
      };
    } catch (error) {
      if (error instanceof ApiError && error.status === 403) showAccessDenied();
      else if (!(error instanceof ApiError && error.status === 401)) showStartupError(error.message || 'We couldn’t load your account. Try again.');
      return null;
    } finally {
      busy = false;
    }
  };
  retry.addEventListener('click', start);
  document.getElementById('refresh-button').addEventListener('click', () => {
    if (!activePage?.refresh) return;
    const button = document.getElementById('refresh-button');
    button.disabled = true;
    button.classList.add('is-loading');
    activePage.refresh().finally(() => {
      button.disabled = false;
      button.classList.remove('is-loading');
    });
  });
  document.getElementById('logout-button').addEventListener('click', async (event) => {
    const button = event.currentTarget;
    button.disabled = true;
    try {
      const response = await fetch('/auth/logout', {
        method: 'POST', credentials: 'same-origin', headers: { Accept: 'application/json' }
      });
      if (!response.ok) throw new Error('Sign out could not be completed. Please try again.');
      window.location.assign('/login');
    } catch (error) {
      button.disabled = false;
      showToast(error.message || 'Unable to sign out. Check your connection and retry.', 'error');
    }
  });
  window.addEventListener('admin:data-refreshed', (event) => setRefreshed(event.detail?.at));
  return start();
}
