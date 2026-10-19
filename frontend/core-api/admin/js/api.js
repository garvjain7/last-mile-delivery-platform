const SAFE_DETAIL_CODES = new Set([
  'csrf', 'reauth_required', 'reauth_failed', 'not_found', 'invalid_state',
  'email_exists', 'owner_inactive', 'name_exists', 'merchant_name_exists', 'warehouse_code_exists',
  'last_admin', 'self_action_blocked', 'driver_has_active_route',
  'warehouse_has_open_orders', 'warehouse_has_active_routes', 'role_not_assignable',
  'user_not_staff', 'unsupported_media_type', 'validation_error', 'rate_limited'
]);

export class ApiError extends Error {
  constructor(message, status, code = null, current = null) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.code = code;
    this.current = current;
  }
}

export function goToLogin() {
  const next = `${window.location.pathname}${window.location.search}`;
  window.location.assign(`/login?next=${encodeURIComponent(next)}`);
}

function messageFor(status, payload) {
  const code = payload && typeof payload.code === 'string' ? payload.code : null;
  if (status === 429) return 'Too many requests. Wait a moment and try again.';
  if (status >= 500) return 'The service is temporarily unavailable. Try again shortly.';
  if (SAFE_DETAIL_CODES.has(code) && typeof payload.detail === 'string') return payload.detail;
  if (status === 403) return 'You don’t have permission for this action.';
  if (status === 404) return 'The requested information could not be found.';
  if (status === 422) return 'Some request information was invalid. Review it and try again.';
  return 'The request could not be completed. Try again.';
}

async function refreshSession() {
  const refresh = async () => {
    try {
      const response = await fetch('/auth/refresh', {
        method: 'POST',
        headers: { Accept: 'application/json' },
        credentials: 'same-origin'
      });
      return response.ok;
    } catch {
      return false;
    }
  };

  if (navigator.locks?.request) {
    return navigator.locks.request('auth-refresh', refresh);
  }
  return refresh();
}

let submitterForRequest = null;
document.addEventListener('submit', (event) => {
  submitterForRequest = event.submitter || null;
  const submitted = submitterForRequest;
  queueMicrotask(() => {
    if (submitterForRequest === submitted) submitterForRequest = null;
  });
}, true);

export async function requestJson(path, options = {}) {
  const submitter = submitterForRequest;
  submitterForRequest = null;
  if (submitter) submitter.disabled = true;

  const headers = new Headers(options.headers || {});
  headers.set('Accept', 'application/json');
  const init = {
    ...options,
    headers,
    credentials: 'same-origin'
  };
  if (Object.hasOwn(options, 'body') && options.body !== undefined) {
    headers.set('Content-Type', 'application/json');
    init.body = JSON.stringify(options.body);
  }

  try {
    let response;
    try {
      response = await fetch(path, init);
    } catch {
      throw new ApiError('Unable to reach the service. Check your connection and retry.', 0);
    }

    if (response.status === 401 && path !== '/auth/refresh') {
      if (await refreshSession()) {
        try {
          response = await fetch(path, init);
        } catch {
          throw new ApiError('Unable to reach the service. Check your connection and retry.', 0);
        }
      }
    }

    if (response.status === 401) {
      goToLogin();
      throw new ApiError('Your session has expired. Sign in again.', 401, 'unauthenticated');
    }

    let payload = null;
    try {
      payload = await response.json();
    } catch {
      payload = null;
    }

    if (response.status === 403) {
      throw new ApiError('You don’t have permission for this action.', 403, payload?.code || 'forbidden', payload?.current || null);
    }
    if (!response.ok) {
      throw new ApiError(messageFor(response.status, payload), response.status, payload?.code || null, payload?.current || null);
    }
    if (payload === null) throw new ApiError('The service returned an unreadable response. Retry in a moment.', 502);
    return payload;
  } finally {
    if (submitter) submitter.disabled = false;
  }
}

export async function postJson(path, body = {}) {
  return requestJson(path, { method: 'POST', body });
}

export async function patchJson(path, body) {
  return requestJson(path, { method: 'PATCH', body });
}
