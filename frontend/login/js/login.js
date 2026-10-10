(function () {
  'use strict';

  var ROLE_FALLBACK_REDIRECTS = {
    admin: '/workspaces/admin/operations',
    dispatcher: '/workspaces/dispatcher/live-dispatch',
    fleet_manager: '/workspaces/fleet-manager/driver-operations',
    merchant: '/workspaces/merchant/order-intake',
    driver: '/workspaces/driver/active-route',
    customer: '/workspaces/customer/delivery-tracking'
  };

  var mode = 'email';

  function $(id) { return document.getElementById(id); }

  function show(id, text) {
    var el = $(id);
    el.textContent = text;
    el.hidden = false;
  }

  function hide(id) {
    var el = $(id);
    el.textContent = '';
    el.hidden = true;
  }

  function cleanPhone(value) {
    return value.trim().replace(/[\s()-]/g, '');
  }

  function safePath(path) {
    return typeof path === 'string' && path.charAt(0) === '/' && path.charAt(1) !== '/' ? path : null;
  }

  function resolveRedirect(data) {
    var direct = safePath(data.redirect_to);
    if (direct) return direct;
    var roles = Array.isArray(data.roles) ? data.roles : [];
    for (var i = 0; i < roles.length; i++) {
      if (ROLE_FALLBACK_REDIRECTS[roles[i]]) return ROLE_FALLBACK_REDIRECTS[roles[i]];
    }
    return '/';
  }

  async function postJson(url, body) {
    var res;
    try {
      res = await fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
        credentials: 'same-origin',
        body: JSON.stringify(body)
      });
    } catch (err) {
      return { ok: false, status: 0, data: {} };
    }
    var data = {};
    try { data = (await res.json()) || {}; } catch (err) { data = {}; }
    return { ok: res.ok, status: res.status, data: data };
  }

  // detailStatuses: HTTP statuses where the server's own message is safe to show.
  function friendly(res, detailStatuses, fallback) {
    if (res.status === 0) return 'We could not reach the server. Check your connection and try again.';
    if (res.status === 429) return 'Too many attempts. Wait a minute and try again.';
    if (res.status >= 500) return 'Something went wrong on our side. Try again in a moment.';
    if (res.status === 422) return 'Check the details you entered and try again.';
    if (detailStatuses.indexOf(res.status) !== -1 && typeof res.data.detail === 'string') return res.data.detail;
    return fallback;
  }

  function setMode(next) {
    mode = next;
    $('tab-email').setAttribute('aria-pressed', String(next === 'email'));
    $('tab-phone').setAttribute('aria-pressed', String(next === 'phone'));
    $('group-email').hidden = next !== 'email';
    $('group-phone').hidden = next !== 'phone';
    $('email').value = '';
    $('phone').value = '';
    hide('error-box');
    hide('status-box');
  }

  function showView(name) {
    var forgot = name === 'reset';
    $('login-view').hidden = forgot;
    $('reset-view').hidden = !forgot;
    hide('error-box');
    hide('status-box');
    hide('reset-error-box');
    hide('reset-status-box');
    (forgot ? $('reset-email') : (mode === 'email' ? $('email') : $('phone'))).focus();
  }

  $('tab-email').addEventListener('click', function () { setMode('email'); });
  $('tab-phone').addEventListener('click', function () { setMode('phone'); });
  $('password-reset').addEventListener('click', function () { showView('reset'); });
  $('back-to-login').addEventListener('click', function () { showView('login'); });

  document.querySelectorAll('.pw-toggle').forEach(function (btn) {
    btn.addEventListener('click', function () {
      var input = $(btn.dataset.for);
      var showing = input.type === 'text';
      input.type = showing ? 'password' : 'text';
      btn.textContent = showing ? 'Show' : 'Hide';
      btn.setAttribute('aria-label', showing ? 'Show password' : 'Hide password');
    });
  });

  $('login-form').addEventListener('submit', async function (event) {
    event.preventDefault();
    hide('error-box');
    hide('status-box');

    var password = $('password').value;
    var payload = { password: password };

    if (mode === 'email') {
      var email = $('email').value.trim();
      if (!email) {
        show('error-box', 'Enter the email address for your account.');
        return;
      }
      payload.email = email;
    } else {
      var phone = cleanPhone($('phone').value);
      if (!phone) {
        show('error-box', 'Enter your phone number with country code, for example +919876543210.');
        return;
      }
      payload.phone = phone;
    }

    if (!password || password.length < 8) {
      show('error-box', 'Password must be at least 8 characters.');
      return;
    }

    var button = $('login-submit');
    button.disabled = true;
    show('status-box', 'Signing you in...');

    var res = await postJson('/auth/login', payload);

    if (res.ok) {
      window.location.assign(resolveRedirect(res.data));
      return;
    }

    hide('status-box');
    show('error-box', friendly(res, [403], 'Incorrect email, phone number or password.'));
    button.disabled = false;
  });

  $('forgot-password-form').addEventListener('submit', async function (event) {
    event.preventDefault();
    hide('reset-error-box');
    hide('reset-status-box');

    var email = $('reset-email').value.trim();
    if (!email) {
      show('reset-error-box', 'Enter your email address.');
      return;
    }

    var button = $('reset-submit');
    button.disabled = true;
    show('reset-status-box', 'Sending reset link...');

    var res = await postJson('/auth/forgot-password', { email: email });

    if (res.ok) {
      show('reset-status-box', 'Reset email sent to ' + email);
      $('forgot-password-form').reset();
    } else {
      hide('reset-status-box');
      show('reset-error-box', friendly(res, [], 'We could not send the reset link. Try again in a moment.'));
    }
    button.disabled = false;
  });
})();