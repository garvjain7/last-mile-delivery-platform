(function () {
  'use strict';

  var ROLE_ENDPOINTS = {
    customer: '/auth/register/customer',
    driver: '/auth/register/driver'
  };

  var ROLE_HINTS = {
    customer: 'Track your parcels and see all your orders in one place.',
    driver: 'Our team reviews every driver application before you can start.'
  };

  var selectedRole = 'customer';

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

  function setRole(role) {
    selectedRole = role;
    document.querySelectorAll('#role-toggle button').forEach(function (btn) {
      btn.setAttribute('aria-pressed', String(btn.dataset.role === role));
    });
    $('role-hint').textContent = ROLE_HINTS[role];
  }

  document.querySelectorAll('#role-toggle button').forEach(function (btn) {
    btn.addEventListener('click', function () { setRole(btn.dataset.role); });
  });

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

  $('register-form').addEventListener('submit', async function (event) {
    event.preventDefault();
    hide('register-error');
    hide('register-status');
    $('confirm_password').removeAttribute('aria-invalid');

    var fullName = $('full_name').value.trim();
    var email = $('email').value.trim();
    var phone = cleanPhone($('phone').value);
    var password = $('password').value;
    var confirmPassword = $('confirm_password').value;

    if (!fullName) {
      show('register-error', 'Enter your full name.');
      return;
    }

    if (!email && !phone) {
      show('register-error', 'Enter an email address or a phone number with country code.');
      return;
    }

    if (password.length < 8) {
      show('register-error', 'Password must be at least 8 characters.');
      return;
    }

    if (password !== confirmPassword) {
      show('register-error', 'Passwords do not match.');
      $('confirm_password').setAttribute('aria-invalid', 'true');
      $('confirm_password').focus();
      return;
    }

    var payload = { full_name: fullName, password: password };
    if (email) payload.email = email;
    if (phone) payload.phone = phone;

    var button = $('register-submit');
    button.disabled = true;
    show('register-status', 'Creating your account...');

    var res = await postJson(ROLE_ENDPOINTS[selectedRole], payload);

    if (res.ok) {
      window.location.assign(safePath(res.data.redirect_to) || '/');
      return;
    }

    hide('register-status');
    show('register-error', friendly(res, [400, 403, 409], 'We could not create your account. Check your details and try again.'));
    button.disabled = false;
  });
})();