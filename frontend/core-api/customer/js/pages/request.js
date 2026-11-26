import { mountCustomerShell } from '/static/shared/js/customer/shell.js';
import { getMe, requestJson } from '/static/shared/js/customer/api.js';

const STORAGE_PREFIX = 'customer-order-request:';

await mountCustomerShell({
  page: 'request',
  title: 'New delivery request',
  render: async (root, shellUser, userId) => {
    const storageKey = `${STORAGE_PREFIX}${userId}`;
    let saved = {};
    try {
      saved = JSON.parse(sessionStorage.getItem(storageKey) || '{}');
    } catch {
      saved = {};
    }
    if (!saved.idempotencyKey) saved.idempotencyKey = crypto.randomUUID();
    sessionStorage.setItem(storageKey, JSON.stringify(saved));

    const form = document.createElement('form');
    form.className = 'customer-form-card';
    form.noValidate = true;
    form.innerHTML = `
      <p class="form-intro">Tell us where to deliver your order and who will receive it.</p>
      <div class="customer-form-grid">
        <label class="customer-field customer-field-wide">Seller
          <select name="seller_id" required><option value="">Choose a seller</option></select>
          <span class="field-error" data-error="seller_id"></span>
        </label>
        <label class="customer-field">Recipient name<input name="recipient_name" autocomplete="name" required maxlength="200">
          <span class="field-error" data-error="recipient_name"></span>
        </label>
        <label class="customer-field">Recipient phone<input name="recipient_phone" type="tel" autocomplete="tel" placeholder="+919876543210" required>
          <span class="field-error" data-error="recipient_phone"></span>
        </label>
        <label class="customer-field customer-field-wide">Delivery address<textarea name="delivery_address" autocomplete="street-address" required minlength="5" maxlength="1000"></textarea>
          <span class="field-error" data-error="delivery_address"></span>
        </label>
        <div class="field-actions customer-field-wide"><button class="secondary-button" type="button" data-location>Use my location</button><span class="location-message" role="status"></span></div>
        <label class="customer-field">Weight (kg)<input name="weight_kg" type="number" min="0.001" step="any" required>
          <span class="field-error" data-error="weight_kg"></span>
        </label>
        <label class="customer-field">Volume (m³)<input name="volume_m3" type="number" min="0.001" step="any" required>
          <span class="field-error" data-error="volume_m3"></span>
        </label>
        <label class="customer-field">Delivery window starts<input name="window_earliest" type="datetime-local">
          <span class="field-error" data-error="window_earliest"></span>
        </label>
        <label class="customer-field">Delivery window ends<input name="window_latest" type="datetime-local">
          <span class="field-error" data-error="window_latest"></span>
        </label>
      </div>
      <p class="request-message" role="status" aria-live="polite"></p>
      <button class="button request-submit" type="submit">Create delivery request</button>`;
    root.append(form);

    const fields = Object.fromEntries([...form.querySelectorAll('[name]')].map((field) => [field.name, field]));
    for (const [name, value] of Object.entries(saved.values || {})) {
      if (fields[name]) fields[name].value = value;
    }

    function saveDraft() {
      const values = Object.fromEntries(Object.entries(fields).map(([name, field]) => [name, field.value]));
      sessionStorage.setItem(storageKey, JSON.stringify({ idempotencyKey: saved.idempotencyKey, values }));
    }
    form.addEventListener('input', saveDraft);
    form.addEventListener('change', saveDraft);

    async function loadFormOptions() {
      const [me, sellers] = await Promise.all([
        getMe({ redirectOnFailure: false }),
        requestJson(`/api/users/${encodeURIComponent(userId)}/request/sellers`),
      ]);
      if (!me) return;
      if (!fields.recipient_name.value) fields.recipient_name.value = me.full_name || shellUser.full_name || '';
      if (!fields.recipient_phone.value) fields.recipient_phone.value = me.phone || '';
      const selectedSeller = fields.seller_id.value;
      fields.seller_id.replaceChildren(new Option('Choose a seller', ''));
      for (const seller of sellers) fields.seller_id.add(new Option(seller.name, seller.id));
      if (selectedSeller || saved.values?.seller_id) fields.seller_id.value = selectedSeller || saved.values.seller_id;
      saveDraft();
    }

    try {
      await loadFormOptions();
    } catch (error) {
      const message = form.querySelector('.request-message');
      message.textContent = error.status === 404
        ? 'This customer page could not be found.'
        : error.message || 'The request form could not be loaded.';
      if (error.status === 404) {
        const link = document.createElement('a');
        link.href = `/users/${encodeURIComponent(userId)}/orders`;
        link.textContent = 'My orders';
        message.append(' ', link);
      }
    }
    const retryOptions = document.createElement('button');
    retryOptions.type = 'button';
    retryOptions.className = 'secondary-button';
    retryOptions.textContent = 'Retry loading sellers';
    retryOptions.hidden = !form.querySelector('.request-message').textContent;
    form.querySelector('.request-message').after(retryOptions);
    retryOptions.addEventListener('click', async () => {
      retryOptions.disabled = true;
      try {
        await loadFormOptions();
        form.querySelector('.request-message').textContent = '';
        retryOptions.hidden = true;
      } catch (error) {
        form.querySelector('.request-message').textContent = error.message || 'The request form could not be loaded.';
      } finally {
        retryOptions.disabled = false;
      }
    });
    window.addEventListener('focus', () => loadFormOptions().catch(() => {}));
    window.addEventListener('pageshow', (event) => {
      if (event.persisted) loadFormOptions().catch(() => {});
    });

    form.querySelector('[data-location]').addEventListener('click', (event) => {
      const button = event.currentTarget;
      const locationMessage = form.querySelector('.location-message');
      if (!navigator.geolocation) {
        locationMessage.textContent = 'Location is unavailable. Enter the address manually.';
        return;
      }
      button.disabled = true;
      locationMessage.textContent = 'Finding your location…';
      navigator.geolocation.getCurrentPosition(async ({ coords }) => {
        try {
          const result = await requestJson(`/api/users/${encodeURIComponent(userId)}/request/address?lat=${encodeURIComponent(coords.latitude)}&lng=${encodeURIComponent(coords.longitude)}`);
          fields.delivery_address.value = result.address;
          saveDraft();
          locationMessage.textContent = 'Address added. Check it before continuing.';
        } catch (error) {
          locationMessage.textContent = error.message || 'We could not find an address here.';
        } finally {
          button.disabled = false;
        }
      }, () => {
        locationMessage.textContent = 'Location is unavailable. Enter the address manually.';
        button.disabled = false;
      }, { timeout: 10000, maximumAge: 60000 });
    });

    form.addEventListener('submit', async (event) => {
      event.preventDefault();
      const submit = form.querySelector('.request-submit');
      const message = form.querySelector('.request-message');
      form.querySelectorAll('.field-error').forEach((node) => { node.textContent = ''; });
      form.querySelectorAll('[aria-invalid="true"]').forEach((node) => node.removeAttribute('aria-invalid'));
      const payload = {
        seller_id: fields.seller_id.value,
        recipient_name: fields.recipient_name.value.trim(),
        recipient_phone: fields.recipient_phone.value.trim(),
        delivery_address: fields.delivery_address.value.trim(),
        weight_kg: Number(fields.weight_kg.value),
        volume_m3: Number(fields.volume_m3.value),
        window_earliest: fields.window_earliest.value ? new Date(fields.window_earliest.value).toISOString() : null,
        window_latest: fields.window_latest.value ? new Date(fields.window_latest.value).toISOString() : null,
      };
      let invalid = false;
      const checks = {
        seller_id: Boolean(payload.seller_id),
        recipient_name: payload.recipient_name.length >= 1 && payload.recipient_name.length <= 200,
        recipient_phone: /^\+[1-9][0-9]{7,14}$/.test(payload.recipient_phone),
        delivery_address: payload.delivery_address.length >= 5 && payload.delivery_address.length <= 1000,
        weight_kg: payload.weight_kg > 0,
        volume_m3: payload.volume_m3 > 0,
      };
      const messages = {
        seller_id: 'Choose a seller.',
        recipient_name: 'Enter the recipient name.',
        recipient_phone: 'Enter a phone number in international format, for example +919876543210.',
        delivery_address: 'Enter a delivery address of at least 5 characters.',
        weight_kg: 'Enter a weight greater than zero.',
        volume_m3: 'Enter a volume greater than zero.',
      };
      for (const [name, valid] of Object.entries(checks)) {
        if (!valid) {
          fields[name].setAttribute('aria-invalid', 'true');
          form.querySelector(`[data-error="${name}"]`).textContent = messages[name];
          invalid = true;
        }
      }
      if (Boolean(payload.window_earliest) !== Boolean(payload.window_latest)) {
        form.querySelector('[data-error="window_earliest"]').textContent = 'Enter both delivery window times, or leave both empty.';
        invalid = true;
      } else if (payload.window_earliest && new Date(payload.window_latest) <= new Date(payload.window_earliest)) {
        form.querySelector('[data-error="window_latest"]').textContent = 'The end time must be after the start time.';
        invalid = true;
      }
      if (invalid) return;

      submit.disabled = true;
      message.textContent = 'Creating your request…';
      saveDraft();
      try {
        const result = await requestJson(`/api/users/${encodeURIComponent(userId)}/request`, {
          method: 'POST',
          headers: { 'Idempotency-Key': saved.idempotencyKey },
          body: payload,
        });
        sessionStorage.removeItem(storageKey);
        location.replace(`/users/${encodeURIComponent(userId)}/orders/${encodeURIComponent(result.order_id)}`);
      } catch (error) {
        if (error.status === 422 && Array.isArray(error.payload?.errors)) {
          for (const item of error.payload.errors) {
            const name = item.field;
            if (fields[name]) {
              fields[name].setAttribute('aria-invalid', 'true');
              form.querySelector(`[data-error="${name}"]`).textContent = item.message;
            }
          }
          message.textContent = 'Review the highlighted fields and try again.';
        } else {
          message.textContent = error.message || 'Your request could not be created. Try again.';
          if (error.status === 404) {
            const link = document.createElement('a');
            link.href = `/users/${encodeURIComponent(userId)}/orders`;
            link.textContent = 'My orders';
            message.append(' ', link);
          }
        }
        submit.disabled = false;
      }
    });
  },
});
