(function () {
  'use strict';

  var INVALID_LINK = 'This reset link is invalid or has expired. Request a new one from the sign-in page.';
  var token = new URLSearchParams(window.location.search).get('token');

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

  function lockForm() {
    $('password').disabled = true;
    $('confirm_password').disabled = true;
    $('reset-submit').disabled = true;
  }

  document.querySelectorAll('.pw-toggle').forEach(function (btn) {
    btn.addEventListener('click', function () {
      var input = $(btn.dataset.for);
      var showing = input.type === 'text';
      input.type = showing ? 'password' : 'text';
      btn.textContent = showing ? 'Show' : 'Hide';
      btn.setAttribute('aria-label', showing ? 'Show password' : 'Hide password');
    });
  });

  ['password', 'confirm_password'].forEach(function (id) {
    $(id).addEventListener('input', function () {
      $('confirm_password').removeAttribute('aria-invalid');
    });
  });

  if (!token) {
    lockForm();
    show('error-box', INVALID_LINK);
  }

  $('reset-form').addEventListener('submit', async function (event) {
    event.preventDefault();
    hide('error-box');
    hide('status-box');
    $('confirm_password').removeAttribute('aria-invalid');

    if (!token) {
      show('error-box', INVALID_LINK);
      return;
    }

    var password = $('password').value;
    var confirmPassword = $('confirm_password').value;

    if (password.length < 8) {
      show('error-box', 'Password must be at least 8 characters.');
      return;
    }

    if (password !== confirmPassword) {
      show('error-box', 'Passwords do not match.');
      $('confirm_password').setAttribute('aria-invalid', 'true');
      $('confirm_password').focus();
      return;
    }

    var button = $('reset-submit');
    button.disabled = true;
    show('status-box', 'Updating your password...');

    var res = await postJson('/auth/reset-password', { token: token, new_password: password });

    if (res.ok) {
      show('status-box', 'Password updated. Redirecting you to sign in...');
      lockForm();
      setTimeout(function () { window.location.assign('/login'); }, 2000);
      return;
    }

    hide('status-box');
    show('error-box', friendly(res, [400], INVALID_LINK));
    button.disabled = false;
  });
})();