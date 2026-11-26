import { statusClass, statusLabel, buildRail } from './status.js';

export function createOrderCard(order, userId) {
  const card = document.createElement('article');
  card.className = 'customer-order-card';
  const heading = document.createElement('div');
  heading.className = 'order-card-heading';
  const title = document.createElement('div');
  const seller = document.createElement('h2');
  seller.textContent = order.seller_name || order.seller?.name || 'Delivery';
  const reference = document.createElement('p');
  reference.textContent = order.merchant_order_ref || order.tracking_token || 'Order';
  title.append(seller, reference);
  const badge = document.createElement('span');
  badge.className = `status-badge ${statusClass(order.status)}`;
  badge.textContent = order.status_label || statusLabel(order.status);
  heading.append(title, badge);

  const footer = document.createElement('div');
  footer.className = 'order-card-footer';
  const created = document.createElement('time');
  created.dateTime = order.created_at;
  created.textContent = order.created_at ? new Date(order.created_at).toLocaleDateString() : '';
  const actions = document.createElement('div');
  actions.className = 'order-card-actions';
  const details = document.createElement('a');
  details.href = `/users/${encodeURIComponent(userId)}/orders/${encodeURIComponent(order.id)}`;
  details.textContent = 'Details';
  actions.append(details);
  if (order.status !== 'delivered') {
    const track = document.createElement('a');
    track.className = 'button button-small';
    track.href = `/track?code=${encodeURIComponent(order.tracking_token)}`;
    track.textContent = 'Track';
    actions.append(track);
  }
  footer.append(created, actions);
  card.append(heading);
  if (order.status) {
    const rail = document.createElement('ol');
    rail.className = 'order-rail';
    for (const step of buildRail(order.status)) {
      const item = document.createElement('li');
      item.className = `rail-step rail-${step.state}`;
      item.textContent = step.label;
      rail.append(item);
    }
    card.append(rail);
  }
  card.append(footer);
  return card;
}
