const LOGIN_URL = '/login';

function internalNext(path = `${location.pathname}${location.search}`) {
  try {
    const target = new URL(path, location.origin);
    return target.origin === location.origin
      ? `${target.pathname}${target.search}${target.hash}`
      : '/';
  } catch {
    return '/';
  }
}

export function goToLogin(path) {
  location.assign(`${LOGIN_URL}?next=${encodeURIComponent(internalNext(path))}`);
}

async function refreshRequest() {
  try {
    const response = await fetch('/auth/refresh', {
      method: 'POST',
      headers: { Accept: 'application/json' },
      credentials: 'same-origin',
    });
    return response.ok;
  } catch {
    return false;
  }
}

export function refreshSession() {
  if (navigator.locks?.request) {
    return navigator.locks.request('auth-refresh', refreshRequest);
  }
  return refreshRequest();
}

export async function requestJson(path, options = {}) {
  const headers = new Headers(options.headers || {});
  headers.set('Accept', 'application/json');
  const init = { ...options, headers, credentials: 'same-origin' };
  if (options.body !== undefined && !(options.body instanceof FormData)) {
    headers.set('Content-Type', 'application/json');
    init.body = JSON.stringify(options.body);
  }

  let response;
  try {
    response = await fetch(path, init);
    if (response.status === 401 && path !== '/auth/refresh' && await refreshSession()) {
      response = await fetch(path, init);
    }
  } catch {
    throw new Error('The service could not be reached. Check your connection and try again.');
  }

  let payload = null;
  try {
    payload = await response.json();
  } catch {
    payload = null;
  }
  if (!response.ok) {
    const error = new Error(payload?.detail?.detail || payload?.detail || 'The request could not be completed.');
    error.status = response.status;
    error.payload = payload;
    if (response.status === 401) goToLogin();
    throw error;
  }
  return payload;
}

export async function getMe({ redirectOnFailure = true } = {}) {
  let response = await fetch('/auth/me', { headers: { Accept: 'application/json' }, credentials: 'same-origin' });
  if (response.status === 401 && await refreshSession()) {
    response = await fetch('/auth/me', { headers: { Accept: 'application/json' }, credentials: 'same-origin' });
  }
  if (response.status === 401) {
    if (redirectOnFailure) goToLogin();
    return null;
  }
  if (!response.ok) throw new Error('Your account could not be loaded.');
  return response.json();
}

export async function logout() {
  return requestJson('/auth/logout', { method: 'POST', body: {} });
}
