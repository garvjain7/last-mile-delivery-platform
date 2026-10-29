import { mountCustomerShell } from '/static/shared/js/customer/shell.js';
import { requestJson } from '/static/shared/js/customer/api.js';
import { statusClass, statusLabel } from '/static/shared/js/customer/status.js';
import { createTimeline } from '/static/shared/js/customer/timeline.js';

await mountCustomerShell({
  page: 'orders',
  title: 'Order details',
  render: async (root, _user, userId) => {
    const orderId = decodeURIComponent(location.pathname.split('/').at(-1) || '');
    const back = document.createElement('a');
    back.className = 'back-link';
    back.href = `/users/${encodeURIComponent(userId)}/orders`;
    back.textContent = '← My orders';
    const state = document.createElement('p');
    state.className = 'message';
    state.textContent = 'Loading order details…';
    root.append(back, state);
    try {
      const order = await requestJson(`/api/users/${encodeURIComponent(userId)}/orders/${encodeURIComponent(orderId)}`);
      state.remove();

      const summary = document.createElement('section');
      summary.className = 'customer-card detail-summary';
      const header = document.createElement('div');
      header.className = 'detail-heading';
      const identity = document.createElement('div');
      identity.innerHTML = '<p class="customer-eyebrow">ORDER</p>';
      const reference = document.createElement('h2');
      reference.textContent = order.merchant_order_ref || order.tracking_token;
      const seller = document.createElement('p');
      seller.textContent = order.seller?.name || 'Seller';
      identity.append(reference, seller);
      const badge = document.createElement('span');
      badge.className = `status-badge ${statusClass(order.status)}`;
      badge.textContent = statusLabel(order.status);
      header.append(identity, badge);

      const codeRow = document.createElement('div');
      codeRow.className = 'tracking-code-row';
      const code = document.createElement('div');
      const codeLabel = document.createElement('span');
      codeLabel.textContent = 'Tracking code';
      const codeValue = document.createElement('strong');
      codeValue.textContent = order.tracking_token;
      code.append(codeLabel, codeValue);
      const copy = document.createElement('button');
      copy.type = 'button';
      copy.className = 'secondary-button';
      copy.textContent = 'Copy code';
      copy.addEventListener('click', async () => {
        try {
          await navigator.clipboard.writeText(order.tracking_token);
          copy.textContent = 'Copied';
        } catch {
          copy.textContent = 'Copy unavailable';
        }
        setTimeout(() => { copy.textContent = 'Copy code'; }, 1500);
      });
      codeRow.append(code, copy);
      summary.append(header, codeRow);
      root.append(summary);

      const timelineCard = document.createElement('section');
      timelineCard.className = 'customer-card detail-card';
      const timelineTitle = document.createElement('h2');
      timelineTitle.textContent = 'Delivery timeline';
      timelineCard.append(timelineTitle, createTimeline(order.steps || []));
      root.append(timelineCard);

      const delivery = document.createElement('section');
      delivery.className = 'customer-card detail-card';
      const deliveryTitle = document.createElement('h2');
      deliveryTitle.textContent = 'Delivery details';
      const fields = [
        ['Recipient', order.recipient_name],
        ['Phone', order.recipient_phone],
        ['Delivery address', order.delivery_address],
        ['Weight', `${order.weight_kg} kg`],
        ['Volume', `${order.volume_m3} m³`],
        ['Delivery window', order.window_earliest && order.window_latest
          ? `${new Date(order.window_earliest).toLocaleString()} – ${new Date(order.window_latest).toLocaleTimeString()}`
          : 'No delivery window selected'],
        ['Placed', new Date(order.created_at).toLocaleString()],
      ];
      const definition = document.createElement('dl');
      definition.className = 'detail-fields';
      for (const [label, value] of fields) {
        const row = document.createElement('div');
        const term = document.createElement('dt');
        term.textContent = label;
        const description = document.createElement('dd');
        description.textContent = value ?? '—';
        row.append(term, description);
        definition.append(row);
      }
      delivery.append(deliveryTitle, definition);
      if (order.status !== 'delivered') {
        const tracking = document.createElement('a');
        tracking.className = 'button detail-track-button';
        tracking.href = `/track?code=${encodeURIComponent(order.tracking_token)}`;
        tracking.textContent = 'Open live tracking';
        delivery.append(tracking);
      }
      root.append(delivery);
    } catch (error) {
      const notFound = error.status === 404;
      state.className = notFound ? 'customer-empty' : 'customer-error';
      state.replaceChildren();
      const heading = document.createElement('h2');
      heading.textContent = notFound ? 'Order not found' : 'Order details are unavailable';
      const text = document.createElement('p');
      text.textContent = notFound ? 'We could not find that order in your account.' : error.message;
      state.append(heading, text, back.cloneNode(true));
      if (!notFound) {
        const retry = document.createElement('button');
        retry.type = 'button';
        retry.className = 'secondary-button';
        retry.textContent = 'Try again';
        retry.addEventListener('click', () => location.reload());
        state.append(retry);
      }
    }
    window.addEventListener('focus', () => location.reload());
    window.addEventListener('pageshow', (event) => {
      if (event.persisted) location.reload();
    });
  },
});
