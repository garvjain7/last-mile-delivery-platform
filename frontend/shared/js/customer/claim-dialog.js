import { requestJson } from './api.js';

export function mountClaimDialog({ userId, onClaimed }) {
  const params = new URLSearchParams(location.search);
  const initialCode = params.get('claim');
  if (initialCode !== null) {
    params.delete('claim');
    const query = params.toString();
    history.replaceState(null, '', `${location.pathname}${query ? `?${query}` : ''}${location.hash}`);
  }

  const dialog = document.createElement('dialog');
  dialog.className = 'claim-dialog';
  dialog.innerHTML = `
    <form method="dialog" class="claim-dialog-card" novalidate>
      <button class="dialog-close" type="button" aria-label="Close">×</button>
      <p class="customer-eyebrow">ADD AN ORDER</p>
      <h2>Claim a guest order</h2>
      <p>Enter the tracking code and recipient phone number used for the delivery.</p>
      <label>Tracking code<input name="tracking_code" autocomplete="off" required></label>
      <label>Recipient phone<input name="recipient_phone" type="tel" autocomplete="tel" required></label>
      <p class="claim-message" role="status" aria-live="polite"></p>
      <button class="button" type="submit">Add order</button>
    </form>`;
  dialog.querySelector('[name="tracking_code"]').value = initialCode || '';
  document.body.append(dialog);

  dialog.querySelector('.dialog-close').addEventListener('click', () => dialog.close());
  dialog.addEventListener('click', (event) => {
    if (event.target === dialog) dialog.close();
  });
  dialog.querySelector('form').addEventListener('submit', async (event) => {
    event.preventDefault();
    const form = event.currentTarget;
    const button = form.querySelector('[type="submit"]');
    const message = form.querySelector('.claim-message');
    const formData = new FormData(form);
    button.disabled = true;
    message.textContent = '';
    try {
      await requestJson(`/api/users/${encodeURIComponent(userId)}/orders/claim`, {
        method: 'POST',
        body: {
          tracking_code: String(formData.get('tracking_code')).trim(),
          recipient_phone: String(formData.get('recipient_phone')).trim(),
        },
      });
      message.textContent = 'Order added to your account.';
      await onClaimed?.();
      dialog.close();
      const toast = document.createElement('div');
      toast.className = 'customer-toast';
      toast.setAttribute('role', 'status');
      toast.textContent = 'Order added to your account';
      document.body.append(toast);
      setTimeout(() => toast.remove(), 3500);
    } catch (error) {
      if (error.status === 404) message.textContent = "We couldn't match that code and phone.";
      else if (error.status === 429) message.textContent = 'Too many attempts, try again later.';
      else message.textContent = error.message || 'The order could not be added. Try again.';
    } finally {
      button.disabled = false;
    }
  });
  if (initialCode !== null) dialog.showModal();
  return { open: () => dialog.showModal(), dialog };
}
